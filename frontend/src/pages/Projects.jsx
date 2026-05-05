import React, { useState } from 'react';
import '../styles/cards.css';
import { useSpring, a } from '@react-spring/web';
import {
  FaJs,
  FaPython,
  FaGithub,
  FaExternalLinkAlt,
  FaJava
} from 'react-icons/fa';
import {
  SiStreamlit,
  SiPandas,
  SiScikitlearn,
  SiApachekafka,
  SiDocker,
  SiMysql,
} from 'react-icons/si';


// Card individual com animação flip
function ProjectCard({ project }) {
  const [flipped, setFlipped] = useState(false);

  const { transform, opacity } = useSpring({
    opacity: flipped ? 1 : 0,
    transform: `perspective(800px) rotateX(${flipped ? 180 : 0}deg)`,
    config: { mass: 5, tension: 500, friction: 80 },
  });

  const toggle = () => setFlipped(state => !state);

  return (
    <div
      className="project-tile"
      role="button"
      tabIndex={0}
      aria-pressed={flipped}
      aria-label={`${project.title} — clique para ver detalhes`}
      onClick={toggle}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggle();
        }
      }}
    >
      <a.div
        className="project-tile__face project-tile__face--front"
        style={{ opacity: opacity.to(o => 1 - o), transform }}
      >
        <header className="project-tile__header">
          <h3 className="project-tile__title">{project.title}</h3>
          <p className="project-tile__description">{project.description}</p>
        </header>
        <footer className="project-tile__chips">
          {project.technologies.map((tech) => (
            <span className="project-tile__chip" key={tech.name}>
              <span className="project-tile__chip-icon" aria-hidden="true">{tech.icon}</span>
              <span className="project-tile__chip-label">{tech.name}</span>
            </span>
          ))}
        </footer>
        <span className="project-tile__hint" aria-hidden="true">toque para detalhes</span>
      </a.div>

      <a.div
        className="project-tile__face project-tile__face--back"
        style={{ opacity, transform: transform.to(t => `${t} rotateX(180deg)`) }}
      >
        <div className="project-tile__back-body">
          <h3 className="project-tile__title project-tile__title--invert">{project.title}</h3>
          <p className="project-tile__details">{project.details}</p>
          {project.features && (
            <ul className="project-tile__features">
              {project.features.map((feature, idx) => (
                <li key={idx}>{feature}</li>
              ))}
            </ul>
          )}
        </div>
        <footer className="project-tile__actions">
          {project.githubUrl && (
            <button
              type="button"
              className="project-tile__action project-tile__action--primary"
              onClick={(e) => { e.stopPropagation(); window.open(project.githubUrl, '_blank', 'noopener'); }}
            >
              <FaGithub aria-hidden="true" /> GitHub
            </button>
          )}
          {project.demoUrl && (
            <button
              type="button"
              className="project-tile__action project-tile__action--success"
              onClick={(e) => { e.stopPropagation(); window.open(project.demoUrl, '_blank', 'noopener'); }}
            >
              <FaExternalLinkAlt aria-hidden="true" /> Demo
            </button>
          )}
        </footer>
      </a.div>
    </div>
  );
}

// IDs estáveis derivados do título — nunca usar índice em listas mutáveis.
const projects = [
  {
    id: 'ideb',
    title: "Análise Educacional - IDEB",
    description: "Análise da importância da inovação nas escolas brasileiras através de dados do IDEB e censo escolar.",
    details: "Dashboard interativo para visualização de dados educacionais, analisando o impacto da tecnologia nas notas e correlação com indicadores do IDEB.",
    technologies: [
      { name: "Streamlit",    icon: <SiStreamlit /> },
      { name: "Pandas",       icon: <SiPandas /> },
      { name: "Matplotlib",   icon: <FaPython /> },
      { name: "Scikit-learn", icon: <SiScikitlearn /> },
    ],
    features: [
      "Dashboard interativo de dados educacionais",
      "Análise de correlação tecnologia x notas",
      "Visualização de indicadores IDEB",
      "Análise de evasão escolar",
    ],
    githubUrl: "https://github.com/danpqdan/analise-dados-educacionais",
    demoUrl:   "https://9vnfumnf7ajvghfs4ttffq.streamlit.app/",
  },
  {
    id: 'analise-py',
    title: "Análise de Dados Python",
    description: "Coleção de projetos em Python focados em análise estatística, automação e visualização de dados.",
    details: "Repositório com múltiplos projetos incluindo automação web, controle comercial, gráficos 3D e análises estatísticas avançadas.",
    technologies: [
      { name: "Python",     icon: <FaPython /> },
      { name: "Tkinter",    icon: <FaJs /> },
      { name: "Matplotlib", icon: <FaPython /> },
      { name: "Pandas",     icon: <SiPandas /> },
    ],
    features: [
      "Automação de processos web",
      "Controle comercial com Tkinter",
      "Visualizações 3D de dados",
      "Análises estatísticas e probabilísticas",
    ],
    githubUrl: "https://github.com/danpqdan/analise_dados-py",
  },
  {
    id: 'chatbot-kafka',
    title: "Chatbot LLM com Kafka",
    description: "Assistente de IA em tempo real com arquitetura de microsserviços e comunicação assíncrona via Kafka.",
    details: "Sistema distribuído em Java com event-driven architecture, WebSocket para client-side e Kafka para alta resiliência e demanda.",
    technologies: [
      { name: "Java",         icon: <FaJava /> },
      { name: "Kafka",        icon: <SiApachekafka /> },
      { name: "WebSocket",    icon: <FaJs /> },
      { name: "Microservices",icon: <SiDocker /> },
    ],
    features: [
      "Arquitetura event-driven",
      "Comunicação WebSocket em tempo real",
      "Alta resiliência com Kafka",
      "Escalabilidade para alta demanda",
    ],
    githubUrl: "https://github.com/danpqdan/chatbot-llm-kafka",
  },
  {
    id: 'helpdesk',
    title: "Sistema Help Desk",
    description: "Sistema desktop para gerenciamento de ordens de serviço com interface intuitiva e geração de relatórios.",
    details: "Aplicação robusta desenvolvida em Python com Tkinter, MySQL e ReportLab para gestão completa de ordens de serviço e relatórios em PDF.",
    technologies: [
      { name: "Python",    icon: <FaPython /> },
      { name: "Tkinter",   icon: <FaJs /> },
      { name: "MySQL",     icon: <SiMysql /> },
      { name: "ReportLab", icon: <FaPython /> },
    ],
    features: [
      "Interface gráfica intuitiva",
      "Gestão completa de ordens de serviço",
      "Relatórios PDF automatizados",
      "Integração com banco MySQL",
    ],
    githubUrl: "https://github.com/danpqdan/desk-help",
    demoUrl:   "https://github.com/danpqdan/desk-help/releases/tag/dist%2Fdist%2Frelease_windows_0.0.1",
  },
];

export default function Projects() {

  return (
    <div className="page-root">
      <div id="projects_card" className="card-carousel project-card">
        <div className="projects-layout">
          <div id="projects_content" className="card-content projects-scrollable">
            <h1 id="projects_title" className="projects-title">Projetos</h1>
            <p id="projects_description" className="projects-lead">
              Clique nos cards para ver mais detalhes de cada projeto.
            </p>

            <div id="projects_list" className="projects-grid">
              {projects.map((project) => (
                <ProjectCard
                  key={project.id}
                  project={project}
                />
              ))}
            </div>
          </div>

          {/* Rodapé com link para GitHub — funcional, não placeholder */}
          <div id="projects_actions" className="projects-footer-bar">
            <a
              href="https://github.com/danpqdan"
              target="_blank"
              rel="noopener noreferrer"
              className="primary-btn"
              aria-label="Ver todos os projetos no GitHub de Daniel Santos"
            >
              <FaGithub aria-hidden="true" style={{ marginRight: '6px' }} />
              Ver no GitHub
            </a>
          </div>
        </div>
      </div>
    </div>
  );

}
