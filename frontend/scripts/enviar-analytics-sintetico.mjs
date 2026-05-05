import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { io } from 'socket.io-client';

const args = process.argv.slice(2);

function obterArg(nome, padrao) {
  const indice = args.indexOf(nome);
  if (indice === -1) return padrao;
  return args[indice + 1] ?? padrao;
}

const url = obterArg('--url', 'http://localhost:5000');
const payloadPath = resolve(
  process.cwd(),
  obterArg('--payload', '../backend/fixtures/analytics_payload_sintetico.json'),
);

function atualizarTimestamps(payload) {
  const timestampFinal = Date.now();
  const timestampInicial = timestampFinal - 7000;
  payload.timestamp_inicial = timestampInicial;
  payload.timestamp_final = timestampFinal;

  for (const sessoes of Object.values(payload.paginas ?? {})) {
    for (const sessao of sessoes) {
      const offsetInicial = sessao.timestamp_inicial - 1760000000000;
      const offsetFinal = sessao.timestamp_final - 1760000000000;
      sessao.timestamp_inicial = timestampInicial + offsetInicial;
      sessao.timestamp_final = timestampInicial + offsetFinal;
    }
  }

  return payload;
}

function calcularResumoEsperado(payload) {
  const resumo = {
    total_visualizacoes: 0,
    total_cliques: 0,
    tempo_total_segundos: 0,
    paginas_visitadas: {},
  };

  for (const [pageId, sessoes] of Object.entries(payload.paginas ?? {})) {
    resumo.paginas_visitadas[pageId] = sessoes.length;
    for (const sessao of sessoes) {
      resumo.total_visualizacoes += Number(sessao.visualizacoes ?? 0);
      resumo.total_cliques += sessao.cliques?.length ?? 0;
      resumo.tempo_total_segundos += Number(sessao.segundos ?? 0);
    }
  }

  return resumo;
}

function compararResumo(esperado, recebido) {
  const campos = ['total_visualizacoes', 'total_cliques', 'tempo_total_segundos', 'paginas_visitadas'];
  const divergencias = {};

  for (const campo of campos) {
    if (JSON.stringify(esperado[campo]) !== JSON.stringify(recebido?.[campo])) {
      divergencias[campo] = {
        esperado: esperado[campo],
        recebido: recebido?.[campo],
      };
    }
  }

  return divergencias;
}

const payload = atualizarTimestamps(JSON.parse(await readFile(payloadPath, 'utf8')));
const esperado = calcularResumoEsperado(payload);

const socket = io(url, {
  transports: ['websocket', 'polling'],
  timeout: 10000,
  extraHeaders: {
    'User-Agent': 'analytics-synthetic-node-client',
    'Accept-Language': 'pt-BR',
  },
});

const timeout = setTimeout(() => {
  console.error('Timeout aguardando analytics_received.');
  socket.disconnect();
  process.exit(1);
}, 15000);

socket.on('connect', () => {
  console.log(`Conectado em ${url}`);
  socket.emit('analytics_data', payload);
});

socket.on('analytics_received', (resposta) => {
  clearTimeout(timeout);
  console.log('analytics_received:');
  console.log(JSON.stringify(resposta, null, 2));

  const divergencias = compararResumo(esperado, resposta.resumo);
  if (Object.keys(divergencias).length > 0) {
    console.error('Divergencias encontradas:');
    console.error(JSON.stringify(divergencias, null, 2));
    socket.disconnect();
    process.exit(1);
  }

  console.log('Resumo recebido bate com o payload sintetico esperado.');
  socket.disconnect();
});

socket.on('analytics_error', (erro) => {
  clearTimeout(timeout);
  console.error('analytics_error:');
  console.error(JSON.stringify(erro, null, 2));
  socket.disconnect();
  process.exit(1);
});

socket.on('connect_error', (erro) => {
  clearTimeout(timeout);
  console.error(`Erro de conexao: ${erro.message}`);
  socket.disconnect();
  process.exit(1);
});
