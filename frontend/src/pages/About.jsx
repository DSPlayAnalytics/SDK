import React from 'react';
import '../styles/cards.css';
import '../styles/about.css';
import perfil from '../assets/img/img_perfil.png';
import { FaJava } from 'react-icons/fa';
import {
  SiSpring,
  SiPython,
  SiDjango,
  SiGit,
} from 'react-icons/si';
import { FiGithub, FiMail, FiPhone, FiTerminal } from 'react-icons/fi';

const SKILLS = [
  { id: 'java',   icon: <FaJava />,    label: 'Java' },
  { id: 'spring', icon: <SiSpring />,  label: 'Spring' },
  { id: 'python', icon: <SiPython />,  label: 'Python' },
  { id: 'django', icon: <SiDjango />,  label: 'Django' },
  { id: 'devops', icon: <FiTerminal />, label: 'DevOps' },
  { id: 'git',    icon: <SiGit />,     label: 'Git' },
];

export default function About() {
  return (
    <div className="page-root">
      <div id="about_card" className="card-carousel about-card">

        {/* Coluna esquerda: avatar, contatos, interesses */}
        <div id="about_left" className="about-left">

          {/* Em mobile (<380px): avatar + texto ficam em linha via CSS */}
          <div className="about-identity">
            <img
              id="about_avatar"
              src={perfil}
              alt="Foto de perfil de Daniel Santos"
              className="avatar"
              width="96"
              height="96"
              loading="lazy"
            />
            <div id="about_text_center" className="about-text-center">
              <h3 id="about_role_title" className="about-h3-large">
                Desenvolvedor / Tech Lead
              </h3>
              <p id="about_meta" className="about-meta">
                5 anos — Java (4y) • Python/Django (1y)
              </p>
            </div>
          </div>

          <div id="about_contact_list" className="contact-list">
            <a
              id="about_link_github"
              href="https://github.com/danpqdan"
              target="_blank"
              rel="noreferrer noopener"
              aria-label="Perfil do GitHub de Daniel Santos"
            >
              <FiGithub aria-hidden="true" /> Github
            </a>
            <a
              id="about_link_email"
              href="mailto:danieltisantos@gmail.com"
              aria-label="Enviar e-mail para Daniel Santos"
            >
              <FiMail aria-hidden="true" /> E-mail
            </a>
            <a
              id="about_link_phone"
              href="tel:+5511962696757"
              aria-label="Ligar para Daniel Santos"
            >
              <FiPhone aria-hidden="true" /> Celular
            </a>
          </div>

          <div id="about_interests_block" className="info-block">
            <div id="about_interests_box" className="info-box">
              <strong id="about_interests_title" className="about-info-strong">
                Interesses:
              </strong>
              <div id="about_interests_text" className="about-info-text">
                Leitura · Comunidades · Meetups
              </div>
            </div>
          </div>
        </div>

        {/* Coluna direita: bio + skills */}
        <div id="about_right" className="card-content about-right">
          <h3 id="about_title" className="about-h3-large tittle">Sobre mim</h3>

          <p id="about_paragraph1" className="about-paragraph">
            Desenvolvedor com 5 anos de experiência, atualmente atuando como
            Tech Lead em um projeto de ERP em uma startup. Conduzo o
            levantamento técnico das demandas do time de produto, apoiando o
            desenho de novas features e a resolução de correções. Promovo
            discussões abertas com o time para alinhar prioridades e definir
            as melhores abordagens em cada decisão.
          </p>

          <p id="about_paragraph2" className="about-paragraph">
            No último ano, ampliei minha atuação para Python e Django,
            desenvolvendo ferramentas internas, automações e integrações.
            Como Tech Lead, contribuo com o time em pipelines de CI/CD,
            observabilidade, segurança em nuvem e métricas — pilares que
            sustentam a evolução contínua e a confiabilidade do sistema.
          </p>

          <p id="about_paragraph3" className="about-paragraph">
            Nas horas livres, dedico tempo à leitura técnica e ficção, à
            participação em comunidades de tecnologia e a apresentações em
            meetups. Invisto na fluência em inglês e em técnicas de
            comunicação para fortalecer minha capacidade de ensinar, escutar
            com atenção e colaborar com pessoas de diferentes contextos.
          </p>

          <div id="about_skills_row" className="skills-row">
            <div id="about_skills_list" className="skills-list">
              <h4 id="about_skills_title" className="about-h4-small">Skills</h4>
              <div id="about_skill_badges" className="skill-badges">
                {SKILLS.map((skill) => (
                  <span
                    key={skill.id}
                    id={`about_skill_${skill.id}`}
                    className="skill-badge"
                    role="img"
                    aria-label={skill.label}
                  >
                    <span className="skill-icon" aria-hidden="true">
                      {skill.icon}
                    </span>
                    <span className="skill-label">{skill.label}</span>
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}