// Intermediário (Cloudflare Worker) para o Palco Karaokê falar com a API do MVSEP.
// O MVSEP não libera chamadas direto do navegador (CORS). Este Worker repassa
// as chamadas de /api/* para o mvsep.com e devolve a resposta com CORS liberado,
// só para o seu site.
//
// Como publicar (grátis):
//   1. Entre em dash.cloudflare.com > Workers & Pages > Create > Create Worker.
//   2. Dê um nome (ex.: mvsep-proxy), clique em Deploy e depois em Edit code.
//   3. Apague o código de exemplo, cole este arquivo inteiro e clique em Deploy.
//   4. Copie o endereço do Worker (algo como https://mvsep-proxy.SEU-USUARIO.workers.dev).
//   5. No app: Separar voz com MVSEP > Avançado > Endereço do servidor, cole esse endereço.

const ORIGENS_PERMITIDAS = [
  'https://matheusbrz.github.io',
  // 'http://localhost:8000', // descomente para testar no seu computador
];
const DESTINO = 'https://mvsep.com';

export default {
  async fetch(request) {
    const origem = request.headers.get('Origin') || '';
    const permitida = ORIGENS_PERMITIDAS.includes(origem);
    const cors = {
      'Access-Control-Allow-Origin': permitida ? origem : ORIGENS_PERMITIDAS[0],
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': '*',
      'Access-Control-Max-Age': '86400',
      'Vary': 'Origin',
    };

    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    if (!permitida) return new Response('Origem não permitida.', { status: 403, headers: cors });

    const url = new URL(request.url);
    if (!url.pathname.startsWith('/api/')) {
      return new Response('Não encontrado.', { status: 404, headers: cors });
    }

    const cabecalhos = new Headers();
    const tipo = request.headers.get('Content-Type');
    if (tipo) cabecalhos.set('Content-Type', tipo);

    const resposta = await fetch(DESTINO + url.pathname + url.search, {
      method: request.method,
      headers: cabecalhos,
      body: request.method === 'GET' || request.method === 'HEAD' ? undefined : request.body,
      redirect: 'follow',
    });

    const saida = new Headers(resposta.headers);
    for (const [k, v] of Object.entries(cors)) saida.set(k, v);
    return new Response(resposta.body, { status: resposta.status, headers: saida });
  },
};
