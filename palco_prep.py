#!/usr/bin/env python3
"""
palco_prep.py: prepara uma música para o Palco Karaokê.

Dado o link de um vídeo do YouTube, o script:
  1. baixa o áudio (yt-dlp);
  2. separa a voz do instrumental (Demucs);
  3. busca a letra sincronizada no LRCLIB, escolhendo a mais próxima da duração do vídeo.

Resultado, dentro de uma pasta "Artista - Música":
  instrumental.mp3   a música sem a voz
  letra.lrc          letra com tempos (ou letra.txt se só existir sem tempos)

No Palco Karaokê, use "Arquivo local" e escolha esses dois arquivos.

Instalação (uma vez):
  pip install -U yt-dlp demucs
  e instale o ffmpeg (Mac: brew install ffmpeg | Windows: winget install ffmpeg | Linux: apt install ffmpeg)

Uso:
  python palco_prep.py "https://www.youtube.com/watch?v=XXXXXXXXXXX"
  python palco_prep.py URL --artist "Fulano" --track "Nome da música"
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "palco-karaoke/1.0 (uso pessoal)"}


def die(msg):
    print("\nErro: " + msg, file=sys.stderr)
    sys.exit(1)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def check_tools():
    if shutil.which("ffmpeg") is None:
        die("ffmpeg não encontrado. Instale o ffmpeg e tente de novo (veja o topo deste arquivo).")
    for mod in ("yt_dlp", "demucs"):
        r = subprocess.run([sys.executable, "-c", "import " + mod], capture_output=True)
        if r.returncode != 0:
            die("o pacote '%s' não está instalado. Rode: pip install -U yt-dlp demucs" % mod.replace("_", "-"))


def video_info(url):
    out = run(
        [sys.executable, "-m", "yt_dlp", "--no-playlist", "--skip-download",
         "--print", "%(title)s\t%(uploader)s\t%(duration)s", url],
        capture_output=True, text=True,
    ).stdout.strip().splitlines()
    if not out:
        die("não consegui ler as informações do vídeo.")
    title, uploader, dur = (out[-1].split("\t") + ["", "", "0"])[:3]
    try:
        dur = float(dur)
    except ValueError:
        dur = 0.0
    return title, uploader, dur


def guess(title, author):
    t = re.sub(
        r"[\(\[][^\)\]]*(official|video|vídeo|lyric|letra|audio|áudio|karaok|instrumental|legendado|clipe|ao vivo|live|hd|4k|remaster)[^\)\]]*[\)\]]",
        "", title or "", flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    artist, track = "", t
    parts = re.split(r"\s+[-–—|]\s+", t)
    if len(parts) >= 2:
        artist, track = parts[0].strip(), " - ".join(parts[1:]).strip()
    elif author:
        artist = re.sub(r"\s*-\s*topic$", "", author, flags=re.I)
        artist = re.sub(r"vevo$", "", artist, flags=re.I).strip()
    track = re.sub(r"\s*[\(\[]?\s*(ft\.?|feat\.?|part\.?)\s.*$", "", track, flags=re.I).strip()
    return artist, track


def lrclib_search(artist, track, duration):
    urls = []
    if track:
        q = "track_name=" + urllib.parse.quote(track)
        if artist:
            q += "&artist_name=" + urllib.parse.quote(artist)
        urls.append("https://lrclib.net/api/search?" + q)
    urls.append("https://lrclib.net/api/search?q=" + urllib.parse.quote((artist + " " + track).strip()))
    found = []
    for u in urls:
        try:
            req = urllib.request.Request(u, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                found += json.loads(r.read().decode("utf-8"))
        except Exception as e:  # rede fora do ar, limite etc.
            print("  aviso: falha ao consultar o LRCLIB (%s)" % e)
        if any(x.get("syncedLyrics") for x in found):
            break
    seen, uniq = set(), []
    for x in found:
        if x.get("instrumental") or not (x.get("syncedLyrics") or x.get("plainLyrics")):
            continue
        if x.get("id") in seen:
            continue
        seen.add(x.get("id"))
        uniq.append(x)

    def diff(x):
        return abs((x.get("duration") or 0) - duration) if duration and x.get("duration") else 0

    uniq.sort(key=lambda x: (0 if x.get("syncedLyrics") else 1, diff(x)))
    return uniq


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "", s).strip() or "musica"


def main():
    ap = argparse.ArgumentParser(description="Prepara instrumental e letra para o Palco Karaokê.")
    ap.add_argument("url", help="link do vídeo do YouTube")
    ap.add_argument("--artist", help="artista (se o título do vídeo não ajudar)")
    ap.add_argument("--track", help="nome da música")
    ap.add_argument("--out", default="palco_musicas", help="pasta de saída (padrão: palco_musicas)")
    ap.add_argument("--model", default="htdemucs", help="modelo do Demucs (padrão: htdemucs)")
    ap.add_argument("--device", help="cpu ou cuda (padrão: automático)")
    ap.add_argument("--keep-vocals", action="store_true", help="guarda também vocals.mp3")
    args = ap.parse_args()

    check_tools()

    print("1/4 Lendo informações do vídeo…")
    title, uploader, duration = video_info(args.url)
    g_artist, g_track = guess(title, uploader)
    artist = args.artist if args.artist is not None else g_artist
    track = args.track if args.track is not None else (g_track or title)
    print("    %s — %s (%d:%02d)" % (artist or "?", track, int(duration) // 60, int(duration) % 60))

    out_dir = Path(args.out) / safe_name((artist + " - " if artist else "") + track)
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="palco_") as tmp:
        work = Path(tmp)

        print("2/4 Baixando o áudio…")
        run([sys.executable, "-m", "yt_dlp", "--no-playlist", "-x", "--audio-format", "wav",
             "-o", str(work / "audio.%(ext)s"), args.url])
        wav = work / "audio.wav"
        if not wav.exists():
            die("o download não gerou o arquivo de áudio.")

        print("3/4 Separando a voz (pode levar alguns minutos, mais rápido com placa de vídeo)…")
        cmd = [sys.executable, "-m", "demucs", "--two-stems=vocals", "--mp3", "--mp3-bitrate", "256",
               "-n", args.model, "-o", str(work / "sep")]
        if args.device:
            cmd += ["-d", args.device]
        cmd.append(str(wav))
        run(cmd)
        stems = list((work / "sep").glob("*/audio/no_vocals.mp3"))
        if not stems:
            die("o Demucs terminou, mas não achei o arquivo do instrumental.")
        shutil.copy(stems[0], out_dir / "instrumental.mp3")
        if args.keep_vocals:
            voc = stems[0].with_name("vocals.mp3")
            if voc.exists():
                shutil.copy(voc, out_dir / "vocals.mp3")

    print("4/4 Buscando a letra no LRCLIB…")
    res = lrclib_search(artist, track, duration)
    if not res:
        print("    Nenhuma letra encontrada. No app, cole a letra manualmente ou refaça com --artist e --track.")
    else:
        best = res[0]
        d = (best.get("duration") or 0) - duration if duration else 0
        if best.get("syncedLyrics"):
            (out_dir / "letra.lrc").write_text(best["syncedLyrics"], encoding="utf-8")
            kind = "letra.lrc"
        else:
            (out_dir / "letra.txt").write_text(best["plainLyrics"], encoding="utf-8")
            kind = "letra.txt (sem tempos)"
        print("    Usei: %s — %s (%+d s de diferença) → %s" % (
            best.get("artistName"), best.get("trackName"), round(d), kind))
        if duration and abs(d) > 5:
            print("    Atenção: a duração difere mais de 5 s. Se a letra sair torta, use o ajuste de tempo no app.")

    print("\nPronto! Arquivos em: %s" % out_dir.resolve())
    print("No Palco Karaokê, abra 'Arquivo local' e escolha instrumental.mp3 e letra.lrc.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        die("um dos passos falhou (%s). Veja a mensagem acima." % (e.cmd[2] if len(e.cmd) > 2 else e.cmd[0]))
    except KeyboardInterrupt:
        die("cancelado.")
