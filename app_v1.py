import os
import uuid
import json
import re
import streamlit as st
from dotenv import load_dotenv
from tinydb import TinyDB, Query
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from PyPDF2 import PdfReader
from openai import OpenAI

# === Carrega variáveis de ambiente ===
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)

# DEBUG opcional
# st.write("OPENAI_API_KEY:", os.getenv("OPENAI_API_KEY"))

api_key = os.getenv("OPENAI_API_KEY", "").strip()
if not api_key:
    st.error("Chave OPENAI_API_KEY não encontrada. Verifique .env sem espaços extras nem aspas.")
    st.stop()

# Inicializa cliente OpenAI
client = OpenAI(api_key=api_key)

# === Classe de Banco de Dados ===
class AnalyzeDatabase(TinyDB):
    def __init__(self, file_path='db.json') -> None:
        super().__init__(file_path)
        self.jobs     = self.table('jobs')
        self.resums   = self.table('resums')
        self.analysis = self.table('analysis')
        self.files    = self.table('files')

    def get_job_by_name(self, name):
        q = Query()
        res = self.jobs.search(q.name == name)
        return res[0] if res else None

    def get_resum_by_id(self, id):
        q = Query()
        res = self.resums.search(q.id == id)
        return res[0] if res else None

    def get_analysis_by_job_id(self, job_id):
        q = Query()
        return self.analysis.search(q.job_id == job_id)

    def get_resums_by_job_id(self, job_id):
        q = Query()
        return self.resums.search(q.job_id == job_id)

    def delete_all_resums_by_job_id(self, job_id):
        q = Query()
        self.resums.remove(q.job_id == job_id)

    def delete_all_analysis_by_job_id(self, job_id):
        q = Query()
        self.analysis.remove(q.job_id == job_id)

    def delete_all_files_by_job_id(self, job_id):
        q = Query()
        self.files.remove(q.job_id == job_id)

# Inicializa o banco de dados
database = AnalyzeDatabase()

# Configuração da página Streamlit
st.set_page_config(layout="wide", page_title="Recrutador", page_icon=":brain:")

# Templates padrão para descrição de vagas
activities = (
    "Participar da definição das tecnologias utilizadas no desenvolvimento dos sistemas\n"
    "Codificar sistemas e aplicações de acordo com padrões e metodologias estabelecidas\n"
    "Estimar prazos para realização das tarefas com base em documentos de requisitos\n"
    "Desenvolver sistemas aplicando as tecnologias definidas pelo time\n"
    "Comentar e documentar o código desenvolvido\n"
    "Criar e aplicar testes unitários\n"
    "Realizar manutenções corretivas em sistemas e aplicações (correção de bugs)"
)
prerequisites = (
    "Conhecimento em Python e Java\n"
    "Experiência com frameworks como Django\n"
    "Familiaridade com Docker, Git e bancos de dados Postgres\n"
    "Conhecimento sobre metodologias ágeis, especialmente Scrum\n"
    "Disponibilidade para trabalho presencial em Florianópolis, SC"
)
differentials = (
    "Conhecimento em Flutter\n"
    "Experiência com Django Rest Framework ou Flask\n"
    "Vivência com pipelines de CI/CD\n"
    "Familiaridade com arquitetura em nuvem (AWS API Gateway, Lambda Functions)\n"
    "Experiência com microserviços, RabbitMQ, Event Source e bancos NoSQL como MongoDB"
)

# === Sidebar: cadastro de vaga e upload de currículos ===
st.sidebar.header("Cadastrar Nova Vaga e Analisar Currículos")
job_name        = st.sidebar.text_input("Nome da Vaga:")
st.sidebar.markdown("**Atividades:**\n" + activities)
st.sidebar.markdown("**Pré-Requisitos:**\n" + prerequisites)
st.sidebar.markdown("**Diferenciais:**\n" + differentials)
job_description = st.sidebar.text_area("Descrição da Vaga (respeitando a estrutura acima):")
uploaded_pdfs   = st.sidebar.file_uploader("Envie currículos em PDF:", type=["pdf"], accept_multiple_files=True)

if st.sidebar.button("Analisar Currículos"):
    if not job_name or not job_description or not uploaded_pdfs:
        st.sidebar.error("Preencha nome, descrição e envie ao menos um PDF.")
    else:
        os.makedirs("uploads", exist_ok=True)
        job_id = str(uuid.uuid4())
        database.jobs.insert({"id": job_id, "name": job_name, "description": job_description})

        for pdf_file in uploaded_pdfs:
            resum_id = str(uuid.uuid4())
            save_path = os.path.join("uploads", f"{resum_id}_{pdf_file.name}")
            with open(save_path, "wb") as f:
                f.write(pdf_file.getbuffer())
            database.files.insert({"id": resum_id, "job_id": job_id, "file": save_path})

            # Extrai texto do PDF
            reader    = PdfReader(save_path)
            full_text = "".join([p.extract_text() or "" for p in reader.pages])

            # Prepara prompt para IA
            prompt = (
                f"Analise este currículo para a vaga '{job_name}'. "
                "Retorne JSON com: name, education, skills (lista), languages (lista), score (0-100), opinion.\n\n"  
                "Currículo:\n" + full_text
            )

            # Chamada à API usando nova interface v1.x
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Você é um sistema de análise de currículos para recrutamento."},
                    {"role": "user",   "content": prompt}
                ]
            )
            raw = resp.choices[0].message.content
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                m = re.search(r"(\{.*\})", raw, re.DOTALL)
                if m:
                    result = json.loads(m.group(1))
                else:
                    st.error(f"Falha ao decodificar JSON:\n{raw}")
                    continue

            # Persiste dados
            database.resums.insert({
                "id": resum_id,
                "job_id": job_id,
                "content": result.get("name"),
                "opinion": result.get("opinion"),
                "file": save_path
            })
            database.analysis.insert({
                "id": str(uuid.uuid4()),
                "job_id": job_id,
                "resum_id": resum_id,
                "name": result.get("name"),
                "education": result.get("education"),
                "skills": result.get("skills"),
                "languages": result.get("languages"),
                "score": result.get("score")
            })
        st.sidebar.success("Análise concluída e salva no TinyDB.")

# === Main Page: visualização das análises ===
st.title("Recrutador")
job_names = [job.get('name') for job in database.jobs.all()]
selected  = st.selectbox("Escolha sua vaga:", job_names)

if selected:
    job      = database.get_job_by_name(selected)
    analyses = database.get_analysis_by_job_id(job.get('id'))
    if analyses:
        import pandas as pd
        df = pd.DataFrame(
            analyses, 
            columns=["name", "education", "skills", "languages", "score", "resum_id", "id"]
        )
        df.rename(columns={
            "name": "Nome", "education": "Educação", "skills": "Habilidades",
            "languages": "Idiomas", "score": "Score", "resum_id": "Resum ID", "id": "ID"
        }, inplace=True)

        # Grid de resultados
        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_pagination(paginationAutoPageSize=True)
        gb.configure_column("Score", sort="desc")
        gb.configure_selection(selection_mode="multiple", use_checkbox=True)
        grid_opts = gb.build()

        st.subheader("Classificação dos Candidatos")
        st.bar_chart(df, x="Nome", y="Score", horizontal=True)

        response = AgGrid(
            df,
            gridOptions=grid_opts,
            enable_enterprise_modules=True,
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            theme="streamlit"
        )
        selected_rows = response.get('selected_rows', [])
        sel_df = pd.DataFrame(selected_rows)

        # Exibe currículos selecionados
        if not sel_df.empty:
            cols = st.columns(len(sel_df))
            for idx, row in enumerate(sel_df.itertuples()):
                resum_data = database.get_resum_by_id(row._2)
                with cols[idx]:
                    st.markdown(resum_data.get('content'))
                    st.markdown(resum_data.get('opnion'))
                    with open(resum_data.get('file'), "rb") as pdf_file:
                        st.download_button(
                            label     = f"Download {resum_data.get('content')}",
                            data      = pdf_file,
                            file_name = os.path.basename(resum_data.get('file')),
                            mime      = "application/pdf"
                        )

        # Botão para limpar dados
        if st.button('Limpar Análise'):
            for r in database.get_resums_by_job_id(job.get('id')):
                if os.path.isfile(r.get('file')):
                    os.remove(r.get('file'))
            database.delete_all_resums_by_job_id(job.get('id'))
            database.delete_all_analysis_by_job_id(job.get('id'))
            database.delete_all_files_by_job_id(job.get('id'))
            st.experimental_rerun()
