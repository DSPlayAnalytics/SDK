import { SiGrafana, SiRedux } from 'react-icons/si';
import { FaReact, FaFonticons } from "react-icons/fa";
import { TbBrandVite } from "react-icons/tb";
import '../styles/cards.css';
import '../styles/home.css';

// ClasseHome é instanciada pelo SlidesCarousel via cardNodesRef — não instanciar aqui
// para evitar dupla inicialização do rastreador de analytics.
export default function Home() {
  return (
    <div className="page-root">
      <div className="card-carousel home-card">
        {/* header */}
        <div className="card-header home-header">
          <h1>Portfólio Pessoal</h1>
          <h3>Controle de Dados &amp; Estatísticas</h3>
        </div>
        {/* content (scrollable) */}
        <div
          onWheel={(e) => { e.stopPropagation(); }}
          onTouchMove={(e) => { e.stopPropagation(); }}
          className="card-content"
          id='home-content'
        >
          <section className="home-section">
            <h3>O projeto</h3>
            <p>
              Este portfólio pessoal inclui um componente para controle de
              dados e estatísticas (visualizáveis via Grafana{' '}
              <SiGrafana
                style={{ color: '#f76b1c', verticalAlign: 'middle', marginLeft: 4 }}
                aria-label="Grafana"
              />
              ). A ideia é centralizar métricas e eventos relevantes sobre
              projetos e interações dos visitantes, transformando-os em
              dashboards que ajudam a entender o comportamento, medir impacto
              e tomar decisões informadas.
            </p>
          </section>

          <section className="home-section">
            <h3>Por que ter uma página pessoal?</h3>
            <p>
              Uma página pessoal funciona como vitrine e central de contatos
              para profissionais que oferecem serviços. Ela ajuda a construir
              credibilidade mostrando projetos, resultados e habilidades de
              forma clara e acessível. Além disso, uma página própria permite
              apresentar estudos de caso, destacar integrações (como o uso do
              Grafana para monitoramento) e oferecer caminhos diretos para
              contratação — tudo isso melhora a percepção de valor e facilita
              a aquisição de clientes.
            </p>
            <p>
              Se você presta serviços técnicos, um portfólio atualizado e um
              painel de estatísticas demonstram não apenas know-how, mas também
              compromisso com qualidade e transparência dos resultados. Este
              portfólio foi desenvolvido com foco em exibir métricas e
              facilitar a apresentação de resultados a clientes.
            </p>
          </section>
        </div>

        {/* footer */}
        <div className="container-home-footer">

          <div className="home-footer">
            <a className="tech-btn" href="https://grafana.com/" target="_blank" rel="noopener noreferrer">
              <SiGrafana style={{ color: '#f76b1c' }} /> Grafana
            </a>
            <a className="tech-btn" href="https://react.dev/" target="_blank" rel="noopener noreferrer">
              <FaReact style={{ color: '#61dafb' }} /> React
            </a>
            <a className="tech-btn" href="https://redux.js.org/" target="_blank" rel="noopener noreferrer">
              <SiRedux style={{ color: '#764abc' }} /> Redux
            </a>
            <a className="tech-btn" href="https://react-icons.github.io/react-icons/" target="_blank" rel="noopener noreferrer">
              <FaFonticons style={{ color: '#61dafb' }} /> icons
            </a>
            <a className="tech-btn" href="https://vite.dev/" target="_blank" rel="noopener noreferrer">
              <TbBrandVite style={{ color: '#64b64f' }} /> Vite
            </a>
          </div>
        </div>
      </div>
    </div >
  );
}
