import streamlit as st
import pandas as pd
from datetime import datetime, date
import plotly.express as px
import json
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Controle de Fretes", layout="wide")

conn = st.connection("gsheets", type=GSheetsConnection)

def ler_aba(aba):
    return conn.read(worksheet=aba, ttl=0)

def salvar_aba(aba, df):
    conn.update(worksheet=aba, data=df)

if "logado" not in st.session_state:
    st.session_state.logado = False
    st.session_state.nome = ""
    st.session_state.perfil = ""

if not st.session_state.logado:
    st.title("🚚 Acesso ao Sistema")
    user = st.text_input("Usuário")
    pwd = st.text_input("Senha", type="password")
    if st.button("Entrar", use_container_width=True):
        df_u = ler_aba("usuarios")
        df_u["username"] = df_u["username"].astype(str).str.strip()
        df_u["senha"] = df_u["senha"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        match = df_u[(df_u["username"] == user.strip()) & (df_u["senha"] == pwd.strip())]
        if not match.empty:
            st.session_state.logado = True
            st.session_state.nome = match.iloc[0]["nome"]
            st.session_state.perfil = match.iloc[0]["perfil"]
            st.rerun()
        else:
            st.error("Usuário ou senha inválidos.")
    st.stop()

st.sidebar.title(f"Olá, {st.session_state.nome}")
menu = ["Lançamentos do Dia", "Relatórios e Gráficos"]
if st.session_state.perfil == "admin":
    menu.append("Administração")

opcao = st.sidebar.radio("Menu", menu)
if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.rerun()

if opcao == "Lançamentos do Dia":
    st.header("📋 Controle Diário")
    data_sel = st.date_input("Data", value=date.today())
    data_str = data_sel.strftime("%Y-%m-%d")

    df_lanc = ler_aba("lancamentos")
    df_cols = ler_aba("colunas_extras")
    lista_extras = df_cols["nome_coluna"].dropna().tolist() if not df_cols.empty else []

    df_dia = df_lanc[df_lanc["data_ref"] == data_str] if not df_lanc.empty else pd.DataFrame()
    if df_dia.empty or "CAIXA" not in df_dia["tipo"].values:
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        novo_id = 1 if df_lanc.empty else int(df_lanc["id"].max()) + 1
        fixos = pd.DataFrame([
            {"id": novo_id, "data_ref": data_str, "tipo": "CAIXA", "qtd": 0, "local": "Caixa", "dinheiro": 0.0, "pix_bradesco": 0.0, "pix_stones": 0.0, "cartao": 0.0, "gorjetas": 0.0, "despesas": 0.0, "obs": "", "extras": "{}", "usuario": "Sistema", "data_hora": agora},
            {"id": novo_id + 1, "data_ref": data_str, "tipo": "DIARIA", "qtd": 0, "local": "Diária", "dinheiro": 0.0, "pix_bradesco": 0.0, "pix_stones": 0.0, "cartao": 0.0, "gorjetas": 0.0, "despesas": 0.0, "obs": "", "extras": "{}", "usuario": "Sistema", "data_hora": agora}
        ])
        df_lanc = pd.concat([df_lanc, fixos], ignore_index=True)
        salvar_aba("lancamentos", df_lanc)
        st.rerun()

    idx_caixa = df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "CAIXA")].index
    idx_diaria = df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "DIARIA")].index

    st.subheader("1. Caixa e Diária")
    c_f1, c_f2 = st.columns(2)
    val_caixa = c_f1.number_input("💰 Dinheiro em Caixa (R$)", value=float(df_lanc.loc[idx_caixa, "dinheiro"].iloc[0]), step=1.0)
    val_diaria = c_f2.number_input("📅 Diária do Dia (R$)", value=abs(float(df_lanc.loc[idx_diaria, "dinheiro"].iloc[0])), step=5.0)
    if st.button("Salvar Caixa e Diária", use_container_width=True):
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        df_lanc.loc[idx_caixa, ["dinheiro", "usuario", "data_hora"]] = [val_caixa, st.session_state.nome, agora]
        df_lanc.loc[idx_diaria, ["dinheiro", "usuario", "data_hora"]] = [-abs(val_diaria), st.session_state.nome, agora]
        salvar_aba("lancamentos", df_lanc)
        st.success("Salvo com sucesso!")
        st.rerun()

    st.divider()

    df_c_dia = df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "CORRIDA")]
    proxima_corrida = len(df_c_dia) + 1

    st.subheader(f"2. Nova Corrida ou Despesa (Corrida Nº {proxima_corrida} do dia)")
    with st.form("novo_reg", clear_on_submit=True):
        st.info(f"🔢 **Corrida automática do dia:** Nº {proxima_corrida}")
        local = st.text_input("Local / Descrição (Ex: Piriquito, Gasolina)")
        dinheiro = st.number_input("Dinheiro (R$)", min_value=0.0, step=1.0)
        pix_brad = st.number_input("PIX Bradesco (R$)", min_value=0.0, step=1.0)
        pix_ston = st.number_input("PIX Stones (R$)", min_value=0.0, step=1.0)
        cartao = st.number_input("Cartão (R$)", min_value=0.0, step=1.0)
        gorjetas = st.number_input("Gorjetas (R$)", min_value=0.0, step=1.0)
        despesas = st.number_input("Despesas - Gasolina/Manut. (R$)", min_value=0.0, step=1.0)
        obs = st.text_input("Observação")

        extras_dict = {}
        for col_n in lista_extras:
            extras_dict[col_n] = st.number_input(f"{col_n} (R$)", min_value=0.0, step=1.0)

        enviado = st.form_submit_button("➕ Adicionar Registro", use_container_width=True)
        if enviado:
            if not local or not local.strip():
                st.warning("Preencha o campo Local / Descrição antes de adicionar.")
            else:
                with st.spinner("Salvando na planilha..."):
                    df_atual = ler_aba("lancamentos")
                    df_atual_dia = df_atual[(df_atual["data_ref"] == data_str) & (df_atual["tipo"] == "CORRIDA")]
                    num_corrida_atual = len(df_atual_dia) + 1
                    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
                    novo_id = 1 if df_atual.empty else int(df_atual["id"].max()) + 1
                    nova_linha = pd.DataFrame([{
                        "id": novo_id, "data_ref": data_str, "tipo": "CORRIDA", "qtd": num_corrida_atual, "local": local.strip(),
                        "dinheiro": dinheiro, "pix_bradesco": pix_brad, "pix_stones": pix_ston, "cartao": cartao,
                        "gorjetas": gorjetas, "despesas": despesas, "obs": obs.strip(), "extras": json.dumps(extras_dict),
                        "usuario": st.session_state.nome, "data_hora": agora
                    }])
                    df_atual = pd.concat([df_atual, nova_linha], ignore_index=True)
                    salvar_aba("lancamentos", df_atual)
                st.success(f"Corrida Nº {num_corrida_atual} registrada com sucesso!")
                st.rerun()

    st.divider()

    st.subheader("3. Registros do Dia")
    df_c = df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "CORRIDA")].copy()
    if not df_c.empty:
        df_c = df_c.sort_values("id").reset_index(drop=True)
        df_c["qtd"] = range(1, len(df_c) + 1)

        for col_n in lista_extras:
            df_c[col_n] = df_c["extras"].apply(lambda x: json.loads(str(x)).get(col_n, 0.0) if pd.notna(x) and str(x).startswith("{") else 0.0)
        
        cols_soma = ["dinheiro", "pix_bradesco", "pix_stones", "cartao", "gorjetas"] + lista_extras
        df_c["Total Linha"] = df_c[cols_soma].sum(axis=1) - df_c["despesas"]
        
        df_exibir = df_c.rename(columns={"qtd": "Corrida Nº"})
        cols_show = ["id", "Corrida Nº", "local", "dinheiro", "pix_bradesco", "pix_stones", "cartao", "gorjetas", "despesas"] + lista_extras + ["Total Linha", "obs", "usuario", "data_hora"]
        st.dataframe(df_exibir[cols_show], use_container_width=True, hide_index=True)

        with st.expander("✏️ Alterar ou Excluir Registro"):
            id_edit = st.selectbox("Escolha o ID", df_c["id"].astype(int).tolist())
            idx_e = df_lanc[df_lanc["id"] == id_edit].index
            ed_loc = st.text_input("Local", value=str(df_lanc.loc[idx_e, "local"].iloc[0]))
            ed_din = st.number_input("Dinheiro", value=float(df_lanc.loc[idx_e, "dinheiro"].iloc[0]))
            ed_brad = st.number_input("PIX Bradesco", value=float(df_lanc.loc[idx_e, "pix_bradesco"].iloc[0]))
            ed_ston = st.number_input("PIX Stones", value=float(df_lanc.loc[idx_e, "pix_stones"].iloc[0]))
            ed_cart = st.number_input("Cartão", value=float(df_lanc.loc[idx_e, "cartao"].iloc[0]))
            ed_gorj = st.number_input("Gorjetas", value=float(df_lanc.loc[idx_e, "gorjetas"].iloc[0]))
            ed_desp = st.number_input("Despesas", value=float(df_lanc.loc[idx_e, "despesas"].iloc[0]))
            obs_val = df_lanc.loc[idx_e, "obs"].iloc[0]
            ed_obs = st.text_input("Obs", value=str(obs_val) if pd.notna(obs_val) else "")

            if st.button("💾 Salvar Alteração", use_container_width=True):
                agora = datetime.now().strftime("%d/%m/%Y %H:%M")
                df_lanc.loc[idx_e, ["local", "dinheiro", "pix_bradesco", "pix_stones", "cartao", "gorjetas", "despesas", "obs", "usuario", "data_hora"]] = [
                    ed_loc, ed_din, ed_brad, ed_ston, ed_cart, ed_gorj, ed_desp, ed_obs, st.session_state.nome, agora
                ]
                salvar_aba("lancamentos", df_lanc)
                st.success("Alterado!")
                st.rerun()

            if st.button("🗑️ Excluir Registro", use_container_width=True):
                df_lanc = df_lanc.drop(idx_e)
                mask_dia_corr = (df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "CORRIDA")
                df_lanc.loc[mask_dia_corr, "qtd"] = range(1, mask_dia_corr.sum() + 1)
                salvar_aba("lancamentos", df_lanc)
                st.warning("Excluído e numeração do dia reorganizada!")
                st.rerun()

    st.divider()
    st.subheader("📊 Resumo do Dia")
    total_corridas_feitas = len(df_c)
    t_din = df_c["dinheiro"].sum() if not df_c.empty else 0.0
    t_pix_c = (df_c["pix_bradesco"].sum() + df_c["pix_stones"].sum() + df_c["cartao"].sum()) if not df_c.empty else 0.0
    t_corr = t_din + t_pix_c
    t_desp = df_c["despesas"].sum() if not df_c.empty else 0.0
    t_gorj = df_c["gorjetas"].sum() if not df_c.empty else 0.0

    st.metric("Total de Corridas Feitas no Dia", f"{total_corridas_feitas}")
    st.metric("1. Total de Dinheiro (no dia)", f"R$ {t_din:.2f}")
    st.metric("2. Total PIX + Cartão", f"R$ {t_pix_c:.2f}")
    st.metric("3. Total Corridas (Dinheiro + PIX + Cartão)", f"R$ {t_corr:.2f}")
    st.metric("4. Total Corridas - Diária", f"R$ {(t_corr - val_diaria):.2f}")
    st.metric("5. Total Caixa + Dinheiro - Diária", f"R$ {(val_caixa + t_din - val_diaria):.2f}")
    st.metric("6. Total Dinheiro - Diária (Acerto Espécie)", f"R$ {(t_din - val_diaria):.2f}")
    st.info(f"**Total Despesas:** R$ {t_desp:.2f} | **Gorjetas:** R$ {t_gorj:.2f}")
    st.success(f"**Lucro Líquido Real (Corridas + Gorjetas - Diária - Despesas): R$ {(t_corr + t_gorj - val_diaria - t_desp):.2f}**")

elif opcao == "Relatórios e Gráficos":
    st.header("📈 Relatórios por Período")
    dt_ini = st.date_input("Data Inicial", value=date.today().replace(day=1))
    dt_fim = st.date_input("Data Final", value=date.today())

    df_lanc = ler_aba("lancamentos")
    if not df_lanc.empty:
        mask = (df_lanc["data_ref"] >= dt_ini.strftime("%Y-%m-%d")) & (df_lanc["data_ref"] <= dt_fim.strftime("%Y-%m-%d"))
        df_p = df_lanc[mask]
        df_c = df_p[df_p["tipo"] == "CORRIDA"].copy()
        df_d = df_p[df_p["tipo"] == "DIARIA"]

        tot_qtd_corridas = len(df_c)
        tot_din = df_c["dinheiro"].sum()
        tot_pix_c = df_c["pix_bradesco"].sum() + df_c["pix_stones"].sum() + df_c["cartao"].sum()
        tot_corr = tot_din + tot_pix_c
        tot_diar = abs(df_d["dinheiro"].sum())
        tot_desp = df_c["despesas"].sum()
        tot_gorj = df_c["gorjetas"].sum()

        st.metric("Total de Corridas no Período", f"{tot_qtd_corridas}")
        st.metric("Faturamento Corridas", f"R$ {tot_corr:.2f}")
        st.metric("Total Dinheiro", f"R$ {tot_din:.2f}")
        st.metric("Total PIX + Cartão", f"R$ {tot_pix_c:.2f}")
        st.metric("Total Diárias", f"R$ {tot_diar:.2f}")
        st.metric("Total Despesas", f"R$ {tot_desp:.2f}")
        st.success(f"**Saldo Líquido do Período: R$ {(tot_corr + tot_gorj - tot_diar - tot_desp):.2f}**")

        if not df_c.empty:
            fig_pie = px.pie(
                names=["Dinheiro", "PIX Bradesco", "PIX Stones", "Cartão"],
                values=[df_c["dinheiro"].sum(), df_c["pix_bradesco"].sum(), df_c["pix_stones"].sum(), df_c["cartao"].sum()],
                title="Entradas por Forma de Pagamento"
            )
            st.plotly_chart(fig_pie, use_container_width=True)

            df_c["Faturamento"] = df_c["dinheiro"] + df_c["pix_bradesco"] + df_c["pix_stones"] + df_c["cartao"]
            df_agrup = df_c.groupby("data_ref")[["Faturamento", "despesas"]].sum().reset_index()
            df_agrup = df_agrup.rename(columns={"despesas": "Despesas", "data_ref": "Data"})
            fig_bar = px.bar(
                df_agrup, x="Data", y=["Faturamento", "Despesas"], barmode="group",
                title="Evolução Diária: Faturamento x Despesas", labels={"value": "Valor (R$)", "variable": "Categoria"}
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        csv = df_p.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
        st.download_button("📥 Baixar Relatório Completo (CSV/Excel)", data=csv, file_name=f"relatorio_{dt_ini}_{dt_fim}.csv", mime="text/csv", use_container_width=True)

elif opcao == "Administração":
    st.header("⚙️ Administração")
    st.subheader("Cadastrar Novo Usuário")
    with st.form("f_user", clear_on_submit=True):
        u_log = st.text_input("Login")
        u_nom = st.text_input("Nome")
        u_sen = st.text_input("Senha")
        u_per = st.selectbox("Perfil", ["operador", "admin"])
        if st.form_submit_button("Criar Usuário"):
            if u_log and u_sen:
                df_u = ler_aba("usuarios")
                novo_u = pd.DataFrame([{"username": u_log.strip(), "senha": str(u_sen).strip(), "nome": u_nom.strip(), "perfil": u_per}])
                salvar_aba("usuarios", pd.concat([df_u, novo_u], ignore_index=True))
                st.success("Usuário criado!")

    st.subheader("Adicionar Nova Coluna")
    with st.form("f_col", clear_on_submit=True):
        n_col = st.text_input("Nome da Coluna (Ex: Pedágio, Vale)")
        if st.form_submit_button("Adicionar Coluna"):
            if n_col:
                df_cols = ler_aba("colunas_extras")
                nova_c = pd.DataFrame([{"nome_coluna": n_col.strip()}])
                salvar_aba("colunas_extras", pd.concat([df_cols, nova_c], ignore_index=True))
                st.success("Coluna criada!")
