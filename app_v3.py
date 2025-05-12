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
api_key = os.getenv("OPENAI_API_KEY", "").strip()
if not api_key:
    st.error("Chave OPENAI_API_KEY não encontrada. Verifique .env sem espaços extras nem aspas.")
    st.stop()
client = OpenAI(api_key=api_key)

# === Helper para converter células em strings ===
def stringify_cell(x):
    if isinstance(x, (list, tuple)):
        return ", ".join(str(item) for item in x)
    if isinstance(x, dict):
        return json.dumps(x)
    return str(x) if x is not None else ""

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

# Inicializa banco e Streamlit
database = AnalyzeDatabase()
st.set_page_config(layout="wide", page_title="Recrutador", page_icon=":brain:")

# Templates de descrição de vagas
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

# Sidebar: cadastro de vaga e upload de currículos
st.sidebar.header("Cadastrar Vaga e Analisar Currículos")
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
            path = os.path.join("uploads", f"{resum_id}_{pdf_file.name}")
            with open(path, "wb") as f:
                f.write(pdf_file.getbuffer())
            database.files.insert({"id": resum_id, "job_id": job_id, "file": path})

            # Extrai texto do PDF
            text = "".join([p.extract_text() or "" for p in PdfReader(path).pages])

            # Prompt para IA
            prompt = (
                f"Analise este currículo para a vaga '{job_name}'. Retorne JSON com: name, education, skills (lista), languages (lista), score (0-100), opinion.\n\nCurrículo:\n" + text
            )

            # Chamada à API OpenAI
            raw = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Você é um sistema de análise de currículos para recrutamento."},
                    {"role": "user",   "content": prompt}
                ]
            ).choices[0].message.content

            # Parse JSON com fallback
            try:
                res = json.loads(raw)
            except json.JSONDecodeError:
                m = re.search(r"(\{.*\})", raw, re.DOTALL)
                res = json.loads(m.group(1)) if m else {}

            # Persiste dados
            database.resums.insert({
                "id": resum_id,
                "job_id": job_id,
                "content": res.get("name"),
                "opinion": res.get("opinion"),
                "file": path
            })
            database.analysis.insert({
                "id":       str(uuid.uuid4()),
                "job_id":   job_id,
                "resum_id": resum_id,
                "name":     res.get("name"),
                "education":res.get("education"),
                "skills":   res.get("skills"),
                "languages":res.get("languages"),
                "score":    res.get("score")
            })
        st.sidebar.success("Análise concluída e salva no TinyDB.")

# Main: ranking e visualização de resultados
st.title("Recrutador")
jobs   = database.jobs.all()
option = st.selectbox("Escolha sua vaga:", [j['name'] for j in jobs])
if option:
    job      = database.get_job_by_name(option)
    analyses = database.get_analysis_by_job_id(job['id'])
    if analyses:
        import pandas as pd
        df = pd.DataFrame(analyses)

        # Ranking
        df = df.sort_values('score', ascending=False).reset_index(drop=True)
        df['Ranking'] = df.index + 1

        # Renomeia colunas
        df = df.rename(columns={
            'name':      'Nome',
            'education': 'Educação',
            'skills':    'Habilidades',
            'languages': 'Idiomas',
            'score':     'Score'
        })

        # Tabela de ranking
        st.subheader("🏆 Ranking de Candidatos")
        st.table(df[['Ranking','Nome','Score']])

        # Gráfico de scores
        st.subheader("Gráfico de Scores")
        st.bar_chart(df, x='Nome', y='Score', horizontal=True)

        # Detalhes interativos com AgGrid
        st.subheader("Detalhes dos Candidatos")
        df_details = df[['resum_id','Nome','Educação','Habilidades','Idiomas','Score']].copy()
        for col in ['Educação','Habilidades','Idiomas']:
            df_details[col] = df_details[col].apply(stringify_cell)

        gb = GridOptionsBuilder.from_dataframe(df_details)
        gb.configure_column('resum_id', hide=True)
        gb.configure_pagination(paginationAutoPageSize=True)
        gb.configure_column('Score', sort='desc')
        gb.configure_selection(selection_mode='multiple', use_checkbox=True)
        grid_opts = gb.build()

        grid_resp = AgGrid(df_details, gridOptions=grid_opts,
                            enable_enterprise_modules=True,
                            update_mode=GridUpdateMode.SELECTION_CHANGED,
                            theme='streamlit')
        selected = grid_resp.get('selected_rows') or []

        if len(selected) > 0:
            cols = st.columns(len(selected))
            for i, row in enumerate(selected):
                resum_id = row.get('resum_id')
                data = database.get_resum_by_id(resum_id)
                with cols[i]:
                    st.markdown(f"### {data['content']}")
                    st.markdown(data['opinion'])
                    with open(data['file'],'rb') as f:
                        st.download_button(label=f"Download {data['content']}",
                                            data=f,
                                            file_name=os.path.basename(data['file']),
                                            mime='application/pdf')

                # Limpar análises
        if st.button('Limpar Análise'):
            for r in database.get_resums_by_job_id(job['id']):
                if os.path.isfile(r['file']): os.remove(r['file'])
            database.delete_all_resums_by_job_id(job['id'])
            database.delete_all_analysis_by_job_id(job['id'])
            database.delete_all_files_by_job_id(job['id'])
            # Tentativa de recarregar a página
            try:
                st.experimental_rerun()
            except AttributeError:
                st.success("Análises limpas. Por favor, recarregue a página para atualizar os dados.")
