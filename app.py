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

def converter_moeda(texto):
    if not texto or not str(texto).strip():
        return 0.0
    limpo = str(texto).replace("R$", "").replace(" ", "").strip()
    if "," in limpo and "." in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif "," in limpo:
        limpo = limpo.replace(",", ".")
    try:
        val = float(limpo)
        return max(0.0, val)
    except ValueError:
        return None

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
            st.session_state.nome = str(match.iloc[0]["nome"]).strip()
            st.session_state.perfil = str(match.iloc[0]["perfil"]).strip().lower()
            st.rerun()
        else:
            st.error("Usuário ou senha inválidos.")
    st.stop()

eh_admin = (st.session_state.perfil == "admin")
usuario_atual = st.session_state.nome

st.sidebar.title(f"Olá, {usuario_atual}")
menu = ["Lançamentos do Dia", "Relatórios e Gráficos"]
if eh_admin:
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

    if not df_lanc.empty:
        df_lanc["usuario"] = df_lanc["usuario"].astype(str).str.strip()

    usuario_filtro_dia = usuario_atual
    if eh_admin:
        df_u_lista = ler_aba("usuarios")
        nomes_cadastrados = sorted(df_u_lista["nome"].dropna().astype(str).str.strip().unique().tolist()) if not df_u_lista.empty else []
        if usuario_atual not in nomes_cadastrados:
            nomes_cadastrados.insert(0, usuario_atual)
        opcoes_filtro = ["Todos os Usuários"] + nomes_cadastrados
        usuario_filtro_dia = st.selectbox("👤 Visualizar dados de:", opcoes_filtro)

    caixa_existente = df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "CAIXA") & (df_lanc["usuario"] == usuario_atual)] if not df_lanc.empty else pd.DataFrame()
    diaria_existente = df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "DIARIA") & (df_lanc["usuario"] == usuario_atual)] if not df_lanc.empty else pd.DataFrame()

    valor_inicial_caixa = float(caixa_existente["dinheiro"].iloc[0]) if not caixa_existente.empty else 0.0
    valor_inicial_diaria = abs(float(diaria_existente["dinheiro"].iloc[0])) if not diaria_existente.empty else 0.0

    st.subheader(f"1. Caixa e Diária ({usuario_atual})")
    c_f1, c_f2 = st.columns(2)
    str_caixa = c_f1.text_input("💰 Dinheiro em Caixa (R$)", value=f"{valor_inicial_caixa:.2f}".replace(".", ",") if valor_inicial_caixa > 0 else "", placeholder="0,00")
    str_diaria = c_f2.text_input("📅 Diária do Dia (R$)", value=f"{valor_inicial_diaria:.2f}".replace(".", ",") if valor_inicial_diaria > 0 else "", placeholder="0,00")

    val_caixa_num = converter_moeda(str_caixa)
    val_diaria_num = converter_moeda(str_diaria)
    val_caixa = val_caixa_num if val_caixa_num is not None else 0.0
    val_diaria = val_diaria_num if val_diaria_num is not None else 0.0

    if st.button("Salvar Caixa e Diária", use_container_width=True):
        if val_caixa_num is None or val_diaria_num is None:
            st.error("Digite valores numéricos válidos para Caixa e Diária (Ex: 50 ou 50,00).")
        else:
            with st.spinner("Salvando Caixa e Diária..."):
                df_atual = ler_aba("lancamentos")
                if not df_atual.empty:
                    df_atual["usuario"] = df_atual["usuario"].astype(str).str.strip()
                agora = datetime.now().strftime("%d/%m/%Y %H:%M")

                idx_c = df_atual[(df_atual["data_ref"] == data_str) & (df_atual["tipo"] == "CAIXA") & (df_atual["usuario"] == usuario_atual)].index if not df_atual.empty else []
                idx_d = df_atual[(df_atual["data_ref"] == data_str) & (df_atual["tipo"] == "DIARIA") & (df_atual["usuario"] == usuario_atual)].index if not df_atual.empty else []

                if len(idx_c) > 0:
                    df_atual.loc[idx_c, ["dinheiro", "usuario", "data_hora"]] = [val_caixa, usuario_atual, agora]
                else:
                    novo_id = 1 if df_atual.empty else int(df_atual["id"].max()) + 1
                    nova_c = pd.DataFrame([{"id": novo_id, "data_ref": data_str, "tipo": "CAIXA", "qtd": 0, "local": "Caixa", "dinheiro": val_caixa, "pix_bradesco": 0.0, "pix_stones": 0.0, "cartao": 0.0, "gorjetas": 0.0, "despesas": 0.0, "obs": "", "extras": "{}", "usuario": usuario_atual, "data_hora": agora}])
                    df_atual = pd.concat([df_atual, nova_c], ignore_index=True)

                if len(idx_d) > 0:
                    df_atual.loc[idx_d, ["dinheiro", "usuario", "data_hora"]] = [-abs(val_diaria), usuario_atual, agora]
                else:
                    novo_id = 1 if df_atual.empty else int(df_atual["id"].max()) + 1
                    nova_d = pd.DataFrame([{"id": novo_id, "data_ref": data_str, "tipo": "DIARIA", "qtd": 0, "local": "Diária", "dinheiro": -abs(val_diaria), "pix_bradesco": 0.0, "pix_stones": 0.0, "cartao": 0.0, "gorjetas": 0.0, "despesas": 0.0, "obs": "", "extras": "{}", "usuario": usuario_atual, "data_hora": agora}])
                    df_atual = pd.concat([df_atual, nova_d], ignore_index=True)

                salvar_aba("lancamentos", df_atual)
            st.success("Caixa e Diária salvos com sucesso!")
            st.rerun()

    st.divider()

    df_c_dia_user = df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "CORRIDA") & (df_lanc["usuario"] == usuario_atual)] if not df_lanc.empty else pd.DataFrame()
    proxima_corrida = len(df_c_dia_user) + 1

    st.subheader(f"2. Nova Corrida ou Despesa (Corrida Nº {proxima_corrida} de {usuario_atual})")
    with st.form("novo_reg", clear_on_submit=True):
        st.info(f"🔢 **Corrida automática do dia:** Nº {proxima_corrida}")
        local = st.text_input("Local / Descrição (Ex: Piriquito, Gasolina)")
        dinheiro_txt = st.text_input("Dinheiro (R$)", placeholder="0,00")
        pix_brad_txt = st.text_input("PIX Bradesco (R$)", placeholder="0,00")
        pix_ston_txt = st.text_input("PIX Stones (R$)", placeholder="0,00")
        cartao_txt = st.text_input("Cartão (R$)", placeholder="0,00")
        gorjetas_txt = st.text_input("Gorjetas (R$)", placeholder="0,00")
        despesas_txt = st.text_input("Despesas - Gasolina/Manut. (R$)", placeholder="0,00")
        obs = st.text_input("Observação")

        extras_txt_dict = {}
        for col_n in lista_extras:
            extras_txt_dict[col_n] = st.text_input(f"{col_n} (R$)", placeholder="0,00")

        enviado = st.form_submit_button("➕ Adicionar Registro", use_container_width=True)
        if enviado:
            dinheiro = converter_moeda(dinheiro_txt)
            pix_brad = converter_moeda(pix_brad_txt)
            pix_ston = converter_moeda(pix_ston_txt)
            cartao = converter_moeda(cartao_txt)
            gorjetas = converter_moeda(gorjetas_txt)
            despesas = converter_moeda(despesas_txt)

            extras_dict = {}
            erro_extra = False
            for col_n, val_txt in extras_txt_dict.items():
                val_conv = converter_moeda(val_txt)
                if val_conv is None:
                    erro_extra = True
                else:
                    extras_dict[col_n] = val_conv

            if not local or not local.strip():
                st.warning("Preencha o campo Local / Descrição antes de adicionar.")
            elif None in [dinheiro, pix_brad, pix_ston, cartao, gorjetas, despesas] or erro_extra:
                st.error("Verifique os valores digitados. Use apenas números e vírgula ou ponto (Ex: 25,50).")
            else:
                with st.spinner("Salvando na planilha..."):
                    df_atual = ler_aba("lancamentos")
                    if not df_atual.empty:
                        df_atual["usuario"] = df_atual["usuario"].astype(str).str.strip()
                        df_atual_dia = df_atual[(df_atual["data_ref"] == data_str) & (df_atual["tipo"] == "CORRIDA") & (df_atual["usuario"] == usuario_atual)]
                    else:
                        df_atual_dia = pd.DataFrame()
                    
                    num_corrida_atual = len(df_atual_dia) + 1
                    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
                    novo_id = 1 if df_atual.empty else int(df_atual["id"].max()) + 1
                    nova_linha = pd.DataFrame([{
                        "id": novo_id, "data_ref": data_str, "tipo": "CORRIDA", "qtd": num_corrida_atual, "local": local.strip(),
                        "dinheiro": dinheiro, "pix_bradesco": pix_brad, "pix_stones": pix_ston, "cartao": cartao,
                        "gorjetas": gorjetas, "despesas": despesas, "obs": obs.strip(), "extras": json.dumps(extras_dict),
                        "usuario": usuario_atual, "data_hora": agora
                    }])
                    df_atual = pd.concat([df_atual, nova_linha], ignore_index=True)
                    salvar_aba("lancamentos", df_atual)
                st.success(f"Corrida Nº {num_corrida_atual} registrada com sucesso!")
                st.rerun()

    st.divider()

    titulo_reg = f"3. Registros do Dia ({usuario_filtro_dia})" if eh_admin else "3. Registros do Dia"
    st.subheader(titulo_reg)

    if not df_lanc.empty:
        if eh_admin and usuario_filtro_dia == "Todos os Usuários":
            df_c = df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "CORRIDA")].copy()
        else:
            alvo_user = usuario_filtro_dia if eh_admin else usuario_atual
            df_c = df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "CORRIDA") & (df_lanc["usuario"] == alvo_user)].copy()
    else:
        df_c = pd.DataFrame()

    if not df_c.empty:
        df_c = df_c.sort_values("id").reset_index(drop=True)
        if not (eh_admin and usuario_filtro_dia == "Todos os Usuários"):
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
            ed_din_txt = st.text_input("Dinheiro", value=f"{float(df_lanc.loc[idx_e, 'dinheiro'].iloc[0]):.2f}".replace(".", ","))
            ed_brad_txt = st.text_input("PIX Bradesco", value=f"{float(df_lanc.loc[idx_e, 'pix_bradesco'].iloc[0]):.2f}".replace(".", ","))
            ed_ston_txt = st.text_input("PIX Stones", value=f"{float(df_lanc.loc[idx_e, 'pix_stones'].iloc[0]):.2f}".replace(".", ","))
            ed_cart_txt = st.text_input("Cartão", value=f"{float(df_lanc.loc[idx_e, 'cartao'].iloc[0]):.2f}".replace(".", ","))
            ed_gorj_txt = st.text_input("Gorjetas", value=f"{float(df_lanc.loc[idx_e, 'gorjetas'].iloc[0]):.2f}".replace(".", ","))
            ed_desp_txt = st.text_input("Despesas", value=f"{float(df_lanc.loc[idx_e, 'despesas'].iloc[0]):.2f}".replace(".", ","))
            obs_val = df_lanc.loc[idx_e, "obs"].iloc[0]
            ed_obs = st.text_input("Obs", value=str(obs_val) if pd.notna(obs_val) else "")

            if st.button("💾 Salvar Alteração", use_container_width=True):
                ed_din = converter_moeda(ed_din_txt)
                ed_brad = converter_moeda(ed_brad_txt)
                ed_ston = converter_moeda(ed_ston_txt)
                ed_cart = converter_moeda(ed_cart_txt)
                ed_gorj = converter_moeda(ed_gorj_txt)
                ed_desp = converter_moeda(ed_desp_txt)

                if None in [ed_din, ed_brad, ed_ston, ed_cart, ed_gorj, ed_desp]:
                    st.error("Verifique os valores digitados na edição. Use apenas números e vírgula ou ponto.")
                else:
                    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
                    dono_original = df_lanc.loc[idx_e, "usuario"].iloc[0]
                    df_lanc.loc[idx_e, ["local", "dinheiro", "pix_bradesco", "pix_stones", "cartao", "gorjetas", "despesas", "obs", "usuario", "data_hora"]] = [
                        ed_loc, ed_din, ed_brad, ed_ston, ed_cart, ed_gorj, ed_desp, ed_obs, dono_original, agora
                    ]
                    salvar_aba("lancamentos", df_lanc)
                    st.success("Alterado!")
                    st.rerun()

            if st.button("🗑️ Excluir Registro", use_container_width=True):
                dono_excluido = df_lanc.loc[idx_e, "usuario"].iloc[0]
                df_lanc = df_lanc.drop(idx_e)
                mask_dia_corr = (df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "CORRIDA") & (df_lanc["usuario"] == dono_excluido)
                df_lanc.loc[mask_dia_corr, "qtd"] = range(1, mask_dia_corr.sum() + 1)
                salvar_aba("lancamentos", df_lanc)
                st.warning("Excluído e numeração do dia reorganizada!")
                st.rerun()

    st.divider()
    titulo_res = f"📊 Resumo do Dia ({usuario_filtro_dia})" if eh_admin else "📊 Resumo do Dia"
    st.subheader(titulo_res)

    if not df_lanc.empty:
        if eh_admin and usuario_filtro_dia == "Todos os Usuários":
            res_caixa = df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "CAIXA")]["dinheiro"].sum()
            res_diaria = abs(df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "DIARIA")]["dinheiro"].sum())
        elif eh_admin:
            res_caixa = df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "CAIXA") & (df_lanc["usuario"] == usuario_filtro_dia)]["dinheiro"].sum()
            res_diaria = abs(df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "DIARIA") & (df_lanc["usuario"] == usuario_filtro_dia)]["dinheiro"].sum())
        else:
            res_caixa = val_caixa
            res_diaria = val_diaria
    else:
        res_caixa = val_caixa if not eh_admin else 0.0
        res_diaria = val_diaria if not eh_admin else 0.0

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
    st.metric("4. Total Corridas - Diária", f"R$ {(t_corr - res_diaria):.2f}")
    st.metric("5. Total Caixa + Dinheiro - Diária", f"R$ {(res_caixa + t_din - res_diaria):.2f}")
    st.metric("6. Total Dinheiro - Diária (Acerto Espécie)", f"R$ {(t_din - res_diaria):.2f}")
    st.info(f"**Total Despesas:** R$ {t_desp:.2f} | **Gorjetas:** R$ {t_gorj:.2f}")
    st.success(f"**Lucro Líquido Real (Corridas + Gorjetas - Diária - Despesas): R$ {(t_corr + t_gorj - res_diaria - t_desp):.2f}**")

elif opcao == "Relatórios e Gráficos":
    st.header("📈 Relatórios por Período")
    c_dt1, c_dt2 = st.columns(2)
    dt_ini = c_dt1.date_input("Data Inicial", value=date.today().replace(day=1))
    dt_fim = c_dt2.date_input("Data Final", value=date.today())

    df_lanc = ler_aba("lancamentos")
    if not df_lanc.empty:
        df_lanc["usuario"] = df_lanc["usuario"].astype(str).str.strip()
        
        if eh_admin:
            df_u_lista = ler_aba("usuarios")
            nomes_cadastrados = sorted(df_u_lista["nome"].dropna().astype(str).str.strip().unique().tolist()) if not df_u_lista.empty else []
            usuarios_nos_dados = sorted(df_lanc["usuario"].dropna().unique().tolist())
            todos_nomes = sorted(list(set(nomes_cadastrados + usuarios_nos_dados)))
            opcoes_rel = ["Todos os Usuários"] + todos_nomes
            filtro_rel_user = st.selectbox("👤 Filtrar Relatório por Usuário:", opcoes_rel)
            if filtro_rel_user != "Todos os Usuários":
                df_lanc = df_lanc[df_lanc["usuario"] == filtro_rel_user]
        else:
            df_lanc = df_lanc[df_lanc["usuario"] == usuario_atual]

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
            # Gráfico 1: Pizza com valor em R$ e percentual
            fig_pie = px.pie(
                names=["Dinheiro", "PIX Bradesco", "PIX Stones", "Cartão"],
                values=[df_c["dinheiro"].sum(), df_c["pix_bradesco"].sum(), df_c["pix_stones"].sum(), df_c["cartao"].sum()],
                title="Entradas por Forma de Pagamento"
            )
            fig_pie.update_traces(
                texttemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>(%{percent})",
                textposition="inside"
            )
            st.plotly_chart(fig_pie, use_container_width=True)

            # Gráfico 2: Evolução Diária com valores exibidos acima de cada barra
            df_c["Faturamento"] = df_c["dinheiro"] + df_c["pix_bradesco"] + df_c["pix_stones"] + df_c["cartao"]
            df_agrup = df_c.groupby("data_ref")[["Faturamento", "despesas"]].sum().reset_index()
            df_agrup = df_agrup.rename(columns={"despesas": "Despesas", "data_ref": "Data"})
            fig_bar = px.bar(
                df_agrup, x="Data", y=["Faturamento", "Despesas"], barmode="group",
                title="Evolução Diária: Faturamento x Despesas", labels={"value": "Valor (R$)", "variable": "Categoria"},
                text_auto=True
            )
            fig_bar.update_traces(texttemplate="R$ %{y:,.2f}", textposition="outside")
            fig_bar.update_layout(uniformtext_minsize=8, uniformtext_mode="show")
            st.plotly_chart(fig_bar, use_container_width=True)

            # Gráfico 3: Comparativo por Motorista com valores exibidos acima de cada barra
            if eh_admin and filtro_rel_user == "Todos os Usuários":
                df_comp = df_c.groupby("usuario")[["Faturamento", "despesas"]].sum().reset_index()
                df_comp = df_comp.rename(columns={"usuario": "Motorista", "despesas": "Despesas"})
                fig_comp = px.bar(
                    df_comp, x="Motorista", y=["Faturamento", "Despesas"], barmode="group",
                    title="Comparativo por Usuário: Faturamento x Despesas", labels={"value": "Valor (R$)", "variable": "Categoria"},
                    text_auto=True
                )
                fig_comp.update_traces(texttemplate="R$ %{y:,.2f}", textposition="outside")
                fig_comp.update_layout(uniformtext_minsize=8, uniformtext_mode="show")
                st.plotly_chart(fig_comp, use_container_width=True)

        csv = df_p.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
        st.download_button("📥 Baixar Relatório Completo (CSV/Excel)", data=csv, file_name=f"relatorio_{dt_ini}_{dt_fim}.csv", mime="text/csv", use_container_width=True)

elif opcao == "Administração" and eh_admin:
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
