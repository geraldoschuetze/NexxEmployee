import os
import uuid
import json
import re
import streamlit as st
from dotenv import load_dotenv
from tinydb import TinyDB, Query
from PyPDF2 import PdfReader
from openai import OpenAI

# === Carrega variáveis de ambiente ===
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)
api_key = os.getenv("OPENAI_API_KEY", "").strip()
if not api_key:
    st.error("Chave OPENAI_API_KEY não encontrada. Verifique .env sem espaços extras nem aspas.")
    st.stop()
client = OpenAI(api_key=api_key)

# === Templates de descrição de vaga ===
activities = """
Participar da definição das tecnologias utilizadas no desenvolvimento dos sistemas
Codificar sistemas e aplicações de acordo com padrões e metodologias estabelecidas
Estimar prazos para realização das tarefas com base em documentos de requisitos
Desenvolver sistemas aplicando as tecnologias definidas pelo time
Comentar e documentar o código desenvolvido
Criar e aplicar testes unitários
Realizar manutenções corretivas em sistemas e aplicações (correção de bugs)
"""
prerequisites = """
Conhecimento em Python e Java
Experiência com frameworks como Django
Familiaridade com Docker, Git e bancos de dados Postgres
Conhecimento sobre metodologias ágeis, especialmente Scrum
Disponibilidade para trabalho presencial em Florianópolis, SC
"""
differentials = """
Conhecimento em Flutter
Experiência com Django Rest Framework ou Flask
Vivência com pipelines de CI/CD
Familiaridade com arquitetura em nuvem (AWS API Gateway, Lambda Functions)
Experiência com microserviços, RabbitMQ, Event Source e bancos NoSQL como MongoDB
"""

# === Caching de funções de IA ===
@st.cache_data(show_spinner="Gerando resumo de currículo...")
def resume_cv(cv_text: str) -> str:
    prompt = f"""
**Solicitação de Resumo de Currículo em Markdown:**

# Currículo do candidato para resumir:

{cv_text}

Por favor, gere um resumo do currículo fornecido, formatado em Markdown, seguindo rigorosamente o modelo abaixo. **Não adicione seções extras, tabelas ou qualquer outro tipo de formatação diferente da especificada.** Preencha cada seção com as informações relevantes, garantindo que o resumo seja preciso e focado.

**Formato de Output Esperado:**
```markdown
## Nome Completo
nome_completo aqui

## Experiência
experiencia aqui

## Habilidades
habilidades aqui

## Educação
educacao aqui

## Idiomas
idiomas aqui
```
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role":"system","content":"Você é um assistente que resume currículos em Markdown."},
            {"role":"user","content":prompt}
        ]
    ).choices[0].message.content
    parts = resp.split("```markdown")
    return parts[1].strip() if len(parts) > 1 else resp.strip()

@st.cache_data(show_spinner="Gerando opinião crítica...")
def generate_opinion(cv_text: str, job_desc: str) -> str:
    prompt = f"""
Por favor, analise o currículo fornecido em relação à descrição da vaga aplicada e crie uma opinião ultra crítica e detalhada. A sua análise deve incluir os seguintes pontos:

1. **Pontos de Alinhamento**: aspectos do currículo que correspondem aos requisitos.
2. **Pontos de Desalinhamento**: onde o candidato não atende à vaga.
3. **Pontos de Atenção**: lacunas, trocas frequentes, etc.

**Currículo Original:**
{cv_text}

**Descrição da Vaga:**
{job_desc}

Formate a resposta de forma profissional, com títulos em destaque.
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role":"system","content":"Você é o recrutador chefe gerando opinião crítica."},
            {"role":"user","content":prompt}
        ]
    ).choices[0].message.content
    return resp.strip()

# === Helper para stringify ===
def stringify_cell(x):
    if isinstance(x, (list, tuple)):
        return ", ".join(str(i) for i in x)
    if isinstance(x, dict):
        return json.dumps(x)
    return str(x) if x is not None else ""

# === Classe de Banco de Dados ===
class AnalyzeDatabase(TinyDB):
    def __init__(self, file_path='db.json'):
        super().__init__(file_path)
        self.jobs     = self.table('jobs')
        self.resums   = self.table('resums')
        self.analysis = self.table('analysis')
        self.files    = self.table('files')
    def get_job_by_name(self, name):
        q=Query();r=self.jobs.search(q.name==name);return r[0] if r else None
    def get_resum_by_id(self, id):
        q=Query();r=self.resums.search(q.id==id);return r[0] if r else None
    def get_analysis_by_job_id(self, job_id):
        q=Query();return self.analysis.search(q.job_id==job_id)
    def get_resums_by_job_id(self, job_id):
        q=Query();return self.resums.search(q.job_id==job_id)
    def delete_all_resums_by_job_id(self, job_id):
        q=Query();self.resums.remove(q.job_id==job_id)
    def delete_all_analysis_by_job_id(self, job_id):
        q=Query();self.analysis.remove(q.job_id==job_id)
    def delete_all_files_by_job_id(self, job_id):
        q=Query();self.files.remove(q.job_id==job_id)

# === Streamlit App ===
database = AnalyzeDatabase()
st.set_page_config(layout="wide", page_title="Recrutador", page_icon=":brain:")

# Sidebar: cadastrar vaga e currículos
st.sidebar.header("Cadastrar Vaga e Analisar Currículos")
job_name        = st.sidebar.text_input("Nome da Vaga:")
st.sidebar.markdown(f"**Atividades:**\n{activities}")
st.sidebar.markdown(f"**Pré-Requisitos:**\n{prerequisites}")
st.sidebar.markdown(f"**Diferenciais:**\n{differentials}")
job_description = st.sidebar.text_area("Descrição da Vaga:")
uploaded = st.sidebar.file_uploader("Envie currículos em PDF:", type=["pdf"], accept_multiple_files=True)
if st.sidebar.button("Analisar Currículos"):
    if not job_name or not job_description or not uploaded:
        st.sidebar.error("Preencha todos os campos e envie ao menos um PDF.")
    else:
        os.makedirs("uploads", exist_ok=True)
        job_id = str(uuid.uuid4())
        database.jobs.insert({"id":job_id,"name":job_name,"description":job_description})
        for pdf in uploaded:
            rid = str(uuid.uuid4()); path=f"uploads/{rid}_{pdf.name}"
            with open(path,"wb") as f: f.write(pdf.getbuffer())
            database.files.insert({"id":rid,"job_id":job_id,"file":path})
            text="".join([p.extract_text() or "" for p in PdfReader(path).pages])
            # JSON analysis
            prompt_json=f"Analise este currículo para '{job_name}' e retorne JSON com name, education, skills, languages, score, opinion.\nCurrículo:\n{text}"
            raw=client.chat.completions.create(model="gpt-4o-mini",messages=[{"role":"user","content":prompt_json}]).choices[0].message.content
            try: data=json.loads(raw)
            except: m=re.search(r"(\{.*\})",raw,re.DOTALL); data=json.loads(m.group(1)) if m else {}
            database.resums.insert({"id":rid,"job_id":job_id,"content":data.get("name"),"file":path})
            database.analysis.insert({"id":str(uuid.uuid4()),"job_id":job_id,"resum_id":rid,
                                        "name":data.get("name"),"education":data.get("education"),
                                        "skills":data.get("skills"),"languages":data.get("languages"),
                                        "score":data.get("score")})
        st.sidebar.success("Análises concluídas.")

# Main: Ranking e detalhes em lista
st.title("Recrutador")
jobs=database.jobs.all()
sel=st.selectbox("Escolha sua vaga:",[j['name'] for j in jobs])
if sel:
    job=database.get_job_by_name(sel)
    analyses=database.get_analysis_by_job_id(job['id'])
    if analyses:
        import pandas as pd
        df=pd.DataFrame(analyses).sort_values('score',ascending=False).reset_index(drop=True)
        df['Ranking']=df.index+1
        df.rename(columns={'name':'Nome','education':'Educação','skills':'Habilidades','languages':'Idiomas','score':'Score'},inplace=True)
        st.subheader("🏆 Ranking de Candidatos")
        st.dataframe(df[['Ranking','Nome','Score']])
        st.subheader("Detalhes dos Candidatos")
        for row in df.itertuples(index=False):
            st.markdown(f"---\n#### {row.Nome} (Ranking: {row.Ranking}, Score: {row.Score})")
            resum=database.get_resum_by_id(row.resum_id)
            text="".join([p.extract_text() or "" for p in PdfReader(resum['file']).pages])
            st.markdown(resume_cv(text))
            st.markdown(generate_opinion(text,job_description))
            with open(resum['file'],'rb') as f:
                st.download_button(f"Download {row.Nome}",f,file_name=os.path.basename(resum['file']),mime="application/pdf")
        if st.button('Limpar Análise'):
            for r in database.get_resums_by_job_id(job['id']): os.remove(r['file'])
            database.delete_all_resums_by_job_id(job['id'])
            database.delete_all_analysis_by_job_id(job['id'])
            database.delete_all_files_by_job_id(job['id'])
            st.experimental_rerun()