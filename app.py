import streamlit as st
import pandas as pd
from datetime import datetime, date
from zoneinfo import ZoneInfo
import plotly.express as px
import json
import time
from streamlit_gsheets import GSheetsConnection
from fpdf import FPDF

st.set_page_config(page_title="Controle de Fretes", layout="wide")

conn = st.connection("gsheets", type=GSheetsConnection)

FUSO_BR = ZoneInfo("America/Sao_Paulo")

def agora_br_str():
    return datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M")

def hoje_br():
    return datetime.now(FUSO_BR).date()

COLS_NUMERICAS = ["dinheiro", "pix_bradesco", "pix_stones", "cartao", "gorjetas", "despesas"]
COLS_TEXTO = ["data_ref", "tipo", "local", "obs", "extras", "usuario", "data_hora", "usuario_alteracao", "data_alteracao"]
ORDEM_COLUNAS_LANC = [
    "id", "data_ref", "tipo", "qtd", "local",
    "dinheiro", "pix_bradesco", "pix_stones", "cartao",
    "gorjetas", "despesas", "obs", "extras",
    "usuario", "data_hora", "usuario_alteracao", "data_alteracao"
]

def normalizar_df_lancamentos(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=ORDEM_COLUNAS_LANC)
    df = df.copy()

    if "usuario_alteracao" not in df.columns:
        df["usuario_alteracao"] = df["usuario"] if "usuario" in df.columns else ""
    if "data_alteracao" not in df.columns:
        df["data_alteracao"] = df["data_hora"] if "data_hora" in df.columns else ""

    for col in COLS_NUMERICAS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)
    for col in COLS_TEXTO:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
            df[col] = df[col].replace({"nan": "", "None": "", "<NA>": ""})

    mask_u_alt_vazio = df["usuario_alteracao"].str.strip() == ""
    df.loc[mask_u_alt_vazio, "usuario_alteracao"] = df.loc[mask_u_alt_vazio, "usuario"]

    mask_d_alt_vazio = df["data_alteracao"].str.strip() == ""
    df.loc[mask_d_alt_vazio, "data_alteracao"] = df.loc[mask_d_alt_vazio, "data_hora"]

    if "usuario" in df.columns:
        df["usuario"] = df["usuario"].str.strip()
    if "usuario_alteracao" in df.columns:
        df["usuario_alteracao"] = df["usuario_alteracao"].str.strip()
    if "id" in df.columns:
        df["id"] = pd.to_numeric(df["id"], errors="coerce").fillna(0).astype(int)
    if "qtd" in df.columns:
        df["qtd"] = pd.to_numeric(df["qtd"], errors="coerce").fillna(0).astype(int)

    cols_finais = [c for c in ORDEM_COLUNAS_LANC if c in df.columns] + [c for c in df.columns if c not in ORDEM_COLUNAS_LANC]
    return df[cols_finais]

@st.cache_data(ttl=60, show_spinner=False)
def _ler_aba_cache(aba):
    for tentativa in range(4):
        try:
            df = conn.read(worksheet=aba, ttl=0)
            if aba == "lancamentos":
                return normalizar_df_lancamentos(df)
            return df
        except Exception as e:
            if tentativa == 3:
                raise e
            time.sleep(1.5 * (tentativa + 1))

def ler_aba(aba):
    return _ler_aba_cache(aba).copy()

def salvar_aba(aba, df):
    if aba == "lancamentos":
        df = normalizar_df_lancamentos(df)
    for tentativa in range(4):
        try:
            conn.update(worksheet=aba, data=df)
            _ler_aba_cache.clear()
            return
        except Exception as e:
            if tentativa == 3:
                raise e
            time.sleep(1.5 * (tentativa + 1))

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

def extrair_origem_despesa(extras_str):
    try:
        if pd.notna(extras_str) and str(extras_str).startswith("{"):
            d = json.loads(str(extras_str))
            return d.get("_origem_despesa", "Cartão / Conta (Não sai do caixa)")
    except Exception:
        pass
    return "Cartão / Conta (Não sai do caixa)"

def extrair_forma_gorjeta(extras_str, row_dinheiro=0.0):
    try:
        if pd.notna(extras_str) and str(extras_str).startswith("{"):
            d = json.loads(str(extras_str))
            if "_forma_gorjeta" in d:
                return d["_forma_gorjeta"]
    except Exception:
        pass
    return "Dinheiro" if float(row_dinheiro) > 0 else "PIX / Cartão"

def fmt_brl(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def limpar_latin1(texto):
    return str(texto).encode("latin-1", "replace").decode("latin-1")

class RelatorioPDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, limpar_latin1(f"Página {self.page_no()} de {{nb}}"), align="C")

def gerar_pdf_relatorio(dt_ini, dt_fim, filtro_user, metricas, df_corridas):
    pdf = RelatorioPDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_fill_color(30, 58, 138)
    pdf.rect(0, 0, 210, 28, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_xy(10, 7)
    pdf.cell(0, 8, limpar_latin1("RELATÓRIO DE CONTROLE DE FRETES"), ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_x(10)
    periodo_txt = f"Período: {dt_ini.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')}  |  Filtro: {filtro_user}  |  Emitido em: {agora_br_str()}"
    pdf.cell(0, 6, limpar_latin1(periodo_txt), ln=True)

    pdf.ln(10)
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, limpar_latin1("1. Resumo Financeiro do Período"), ln=True)
    pdf.ln(1)

    pdf.set_font("Helvetica", "", 10)
    total_entradas_geral = metricas["tot_corr"] + metricas["tot_gorj"]
    linhas_resumo = [
        ("Total de Corridas Realizadas", f"{metricas['qtd_corridas']}"),
        ("Faturamento Bruto (Corridas)", fmt_brl(metricas["tot_corr"])),
        ("Total em Dinheiro (Corridas + Gorjetas em Dinheiro)", fmt_brl(metricas["tot_din_com_gorj"])),
        ("Total PIX + Cartão (Corridas + Gorjetas Digitais)", fmt_brl(metricas["tot_pix_com_gorj"])),
        ("Total Gorjetas (Dinheiro: " + fmt_brl(metricas["gorj_din"]) + " | Digital: " + fmt_brl(metricas["gorj_dig"]) + ")", fmt_brl(metricas["tot_gorj"])),
        ("Entrada de Formas de Pagamento + Gorjetas", fmt_brl(total_entradas_geral)),
        ("Total Diárias (Custo Operacional)", fmt_brl(metricas["tot_diar"])),
        ("Despesas Pagas em Dinheiro (Sai do Caixa)", fmt_brl(metricas["desp_caixa"])),
        ("Despesas no Cartão / Conta (Informativo)", fmt_brl(metricas["desp_cartao"])),
        ("Total Geral de Despesas", fmt_brl(metricas["tot_desp"])),
        ("Resultado Operacional (Faturamento + Gorjetas - Diárias)", fmt_brl(metricas["res_operacional"])),
        ("Lucro Líquido Real de Caixa (Descontando só Desp. Dinheiro)", fmt_brl(metricas["lucro_real"])),
    ]

    for idx, (label, val) in enumerate(linhas_resumo):
        destaque_verde = idx >= 10
        destaque_azul = idx == 5
        if destaque_verde:
            pdf.set_fill_color(220, 252, 231)
            pdf.set_font("Helvetica", "B", 10)
        elif destaque_azul:
            pdf.set_fill_color(219, 234, 254)
            pdf.set_font("Helvetica", "B", 10)
        else:
            pdf.set_fill_color(245, 247, 250) if idx % 2 == 0 else pdf.set_fill_color(255, 255, 255)
            pdf.set_font("Helvetica", "", 9.5)
        pdf.cell(135, 7, limpar_latin1(f"  {label}"), border=1, fill=True)
        pdf.cell(55, 7, limpar_latin1(f"{val}  "), border=1, align="R", fill=True, ln=True)

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, limpar_latin1("2. Detalhamento dos Lançamentos (Corridas e Despesas)"), ln=True)
    pdf.ln(1)

    if df_corridas.empty:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 8, limpar_latin1("Nenhum lançamento registrado no período selecionado."), ln=True)
    else:
        pdf.set_fill_color(30, 58, 138)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 8)
        w = [20, 44, 22, 20, 20, 22, 20, 22]
        headers = ["Data", "Local / Desc.", "Motorista", "Dinheiro", "PIX/Cart.", "Gorjeta", "Despesa", "Origem Desp."]
        for i, h in enumerate(headers):
            pdf.cell(w[i], 7, limpar_latin1(h), border=1, align="C", fill=True)
        pdf.ln()

        pdf.set_text_color(20, 20, 20)
        pdf.set_font("Helvetica", "", 7.5)
        df_ord = df_corridas.sort_values(["data_ref", "id"])
        
        soma_col_din = 0.0
        soma_col_pix_cart = 0.0
        soma_col_gorj = 0.0
        soma_col_desp = 0.0

        for row_idx, (_, r) in enumerate(df_ord.iterrows()):
            fill = row_idx % 2 == 1
            pdf.set_fill_color(248, 250, 252) if fill else pdf.set_fill_color(255, 255, 255)
            
            try:
                dt_fmt = datetime.strptime(str(r["data_ref"]), "%Y-%m-%d").strftime("%d/%m/%Y")
            except Exception:
                dt_fmt = str(r["data_ref"])

            din_val = float(r["dinheiro"])
            pix_cart_val = float(r["pix_bradesco"]) + float(r["pix_stones"]) + float(r["cartao"])
            desp_val = float(r["despesas"])
            gorj_val = float(r["gorjetas"])

            soma_col_din += din_val
            soma_col_pix_cart += pix_cart_val
            soma_col_gorj += gorj_val
            soma_col_desp += desp_val
            
            gorj_txt = "0.00"
            if gorj_val > 0:
                f_gorj = extrair_forma_gorjeta(r.get("extras", "{}"), din_val)
                tag_g = "Din" if f_gorj == "Dinheiro" else "Dig"
                gorj_txt = f"{gorj_val:.2f} ({tag_g})"

            origem_curta = "-"
            if desp_val > 0:
                orig = extrair_origem_despesa(r.get("extras", "{}"))
                origem_curta = "Dinheiro" if "Dinheiro" in orig else "Cartão/Conta"

            loc_txt = str(r["local"])[:24]
            mot_txt = str(r["usuario"])[:12]

            pdf.cell(w[0], 6, limpar_latin1(dt_fmt), border=1, align="C", fill=fill)
            pdf.cell(w[1], 6, limpar_latin1(f" {loc_txt}"), border=1, align="L", fill=fill)
            pdf.cell(w[2], 6, limpar_latin1(mot_txt), border=1, align="C", fill=fill)
            pdf.cell(w[3], 6, limpar_latin1(f"{din_val:.2f}"), border=1, align="R", fill=fill)
            pdf.cell(w[4], 6, limpar_latin1(f"{pix_cart_val:.2f}"), border=1, align="R", fill=fill)
            pdf.cell(w[5], 6, limpar_latin1(gorj_txt), border=1, align="R", fill=fill)
            pdf.cell(w[6], 6, limpar_latin1(f"{desp_val:.2f}"), border=1, align="R", fill=fill)
            pdf.cell(w[7], 6, limpar_latin1(origem_curta), border=1, align="C", fill=fill)
            pdf.ln()

        pdf.set_fill_color(226, 232, 240)
        pdf.set_text_color(15, 23, 42)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(w[0] + w[1] + w[2], 7, limpar_latin1(" TOTAL GERAL DOS LANÇAMENTOS"), border=1, align="L", fill=True)
        pdf.cell(w[3], 7, limpar_latin1(f"{soma_col_din:,.2f}"), border=1, align="R", fill=True)
        pdf.cell(w[4], 7, limpar_latin1(f"{soma_col_pix_cart:,.2f}"), border=1, align="R", fill=True)
        pdf.cell(w[5], 7, limpar_latin1(f"{soma_col_gorj:,.2f}"), border=1, align="R", fill=True)
        pdf.cell(w[6], 7, limpar_latin1(f"{soma_col_desp:,.2f}"), border=1, align="R", fill=True)
        pdf.cell(w[7], 7, limpar_latin1("-"), border=1, align="C", fill=True)
        pdf.ln()

    return bytes(pdf.output())

if "logado" not in st.session_state:
    st.session_state.logado = False
    st.session_state.nome = ""
    st.session_state.perfil = ""

if "form_seq" not in st.session_state:
    st.session_state.form_seq = 0

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
if st.sidebar.button("🔄 Atualizar Planilha"):
    _ler_aba_cache.clear()
    st.rerun()
if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.rerun()

if opcao == "Lançamentos do Dia":
    st.header("📋 Controle Diário")
    data_sel = st.date_input("Data", value=hoje_br())
    data_str = data_sel.strftime("%Y-%m-%d")

    df_lanc = ler_aba("lancamentos")
    df_cols = ler_aba("colunas_extras")
    lista_extras = df_cols["nome_coluna"].dropna().tolist() if not df_cols.empty else []

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

    c_btn1, c_btn2 = st.columns([3, 1])
    if c_btn1.button("💾 Salvar Caixa e Diária", use_container_width=True):
        if val_caixa_num is None or val_diaria_num is None:
            st.error("Digite valores numéricos válidos para Caixa e Diária (Ex: 50 ou 50,00).")
        else:
            with st.spinner("Salvando Caixa e Diária..."):
                _ler_aba_cache.clear()
                df_atual = ler_aba("lancamentos")
                agora = agora_br_str()

                idx_c = df_atual[(df_atual["data_ref"] == data_str) & (df_atual["tipo"] == "CAIXA") & (df_atual["usuario"] == usuario_atual)].index if not df_atual.empty else []
                idx_d = df_atual[(df_atual["data_ref"] == data_str) & (df_atual["tipo"] == "DIARIA") & (df_atual["usuario"] == usuario_atual)].index if not df_atual.empty else []

                if len(idx_c) > 0:
                    df_atual.loc[idx_c, "dinheiro"] = float(val_caixa)
                    df_atual.loc[idx_c, "usuario_alteracao"] = str(usuario_atual)
                    df_atual.loc[idx_c, "data_alteracao"] = str(agora)
                else:
                    novo_id = 1 if df_atual.empty else int(df_atual["id"].max()) + 1
                    nova_c = pd.DataFrame([{
                        "id": novo_id, "data_ref": data_str, "tipo": "CAIXA", "qtd": 0, "local": "Caixa",
                        "dinheiro": float(val_caixa), "pix_bradesco": 0.0, "pix_stones": 0.0, "cartao": 0.0,
                        "gorjetas": 0.0, "despesas": 0.0, "obs": "", "extras": "{}",
                        "usuario": str(usuario_atual), "data_hora": str(agora),
                        "usuario_alteracao": str(usuario_atual), "data_alteracao": str(agora)
                    }])
                    df_atual = pd.concat([df_atual, nova_c], ignore_index=True)

                if len(idx_d) > 0:
                    df_atual.loc[idx_d, "dinheiro"] = float(-abs(val_diaria))
                    df_atual.loc[idx_d, "usuario_alteracao"] = str(usuario_atual)
                    df_atual.loc[idx_d, "data_alteracao"] = str(agora)
                else:
                    novo_id = 1 if df_atual.empty else int(df_atual["id"].max()) + 1
                    nova_d = pd.DataFrame([{
                        "id": novo_id, "data_ref": data_str, "tipo": "DIARIA", "qtd": 0, "local": "Diária",
                        "dinheiro": float(-abs(val_diaria)), "pix_bradesco": 0.0, "pix_stones": 0.0, "cartao": 0.0,
                        "gorjetas": 0.0, "despesas": 0.0, "obs": "", "extras": "{}",
                        "usuario": str(usuario_atual), "data_hora": str(agora),
                        "usuario_alteracao": str(usuario_atual), "data_alteracao": str(agora)
                    }])
                    df_atual = pd.concat([df_atual, nova_d], ignore_index=True)

                salvar_aba("lancamentos", df_atual)
            st.success("Caixa e Diária salvos com sucesso!")
            st.rerun()

    tem_caixa_ou_diaria = (not caixa_existente.empty) or (not diaria_existente.empty)
    if c_btn2.button("🗑️ Excluir Caixa/Diária", use_container_width=True, disabled=not tem_caixa_ou_diaria):
        with st.spinner("Excluindo Caixa e Diária..."):
            _ler_aba_cache.clear()
            df_atual = ler_aba("lancamentos")
            if not df_atual.empty:
                mask_remover = (df_atual["data_ref"] == data_str) & (df_atual["usuario"] == usuario_atual) & (df_atual["tipo"].isin(["CAIXA", "DIARIA"]))
                df_atual = df_atual[~mask_remover]
                salvar_aba("lancamentos", df_atual)
        st.warning("Registros de Caixa e Diária excluídos para esta data!")
        st.rerun()

    st.divider()

    df_c_dia_user = df_lanc[(df_lanc["data_ref"] == data_str) & (df_lanc["tipo"] == "CORRIDA") & (df_lanc["usuario"] == usuario_atual)] if not df_lanc.empty else pd.DataFrame()
    proxima_corrida = len(df_c_dia_user) + 1

    opcoes_tipo_lanc = [
        "Dinheiro",
        "PIX Bradesco",
        "PIX Stones",
        "Cartão",
        "Despesas (Gasolina/Manut.)"
    ] + lista_extras

    st.subheader(f"2. Nova Corrida ou Despesa (Corrida Nº {proxima_corrida} de {usuario_atual})")
    st.info(f"🔢 **Corrida automática do dia:** Nº {proxima_corrida}")

    seq = st.session_state.form_seq
    local = st.text_input("Local / Descrição (Ex: Piriquito, Gasolina)", key=f"in_local_{seq}")

    c_v1, c_v2, c_v3 = st.columns([2, 1.5, 1.5])
    tipo_pagamento = c_v1.selectbox("Forma de Pagamento / Tipo", opcoes_tipo_lanc, key=f"in_tipo_{seq}")
    valor_txt = c_v2.text_input("Valor (R$)", placeholder="0,00", key=f"in_valor_{seq}")
    gorjetas_txt = c_v3.text_input("Gorjeta (R$)", placeholder="0,00", key=f"in_gorjeta_{seq}")

    gorjeta_temp = converter_moeda(gorjetas_txt)
    forma_gorjeta_default = 0 if tipo_pagamento == "Dinheiro" else 1
    if gorjeta_temp is not None and gorjeta_temp > 0:
        forma_gorjeta = st.radio(
            "🪙 Como a gorjeta foi recebida?",
            ["Dinheiro", "PIX / Cartão"],
            index=forma_gorjeta_default,
            horizontal=True,
            key=f"in_fgorj_{seq}"
        )
    else:
        forma_gorjeta = "Dinheiro" if tipo_pagamento == "Dinheiro" else "PIX / Cartão"

    origem_despesa = "Cartão / Conta (Não sai do caixa)"
    if tipo_pagamento == "Despesas (Gasolina/Manut.)":
        origem_despesa = st.radio(
            "💳 Como essa despesa foi paga?",
            ["Cartão / Conta (Não sai do caixa)", "Dinheiro do Caixa (Sai da gaveta/espécie)"],
            horizontal=True,
            key=f"in_orig_desp_{seq}"
        )

    pag_misto = st.checkbox("🔀 Pagamento dividido (Ex: parte em Dinheiro + parte em PIX)", key=f"in_misto_{seq}")
    if pag_misto:
        c_m1, c_m2 = st.columns([2, 3])
        tipo_pagamento_2 = c_m1.selectbox("2ª Forma de Pagamento / Tipo", opcoes_tipo_lanc, index=1, key=f"in_tipo2_{seq}")
        valor2_txt = c_m2.text_input("2º Valor (R$)", placeholder="0,00", key=f"in_valor2_{seq}")
        if tipo_pagamento_2 == "Despesas (Gasolina/Manut.)" and tipo_pagamento != "Despesas (Gasolina/Manut.)":
            origem_despesa = st.radio(
                "💳 Como essa despesa foi paga?",
                ["Cartão / Conta (Não sai do caixa)", "Dinheiro do Caixa (Sai da gaveta/espécie)"],
                horizontal=True,
                key=f"in_orig_desp2_{seq}"
            )
    else:
        tipo_pagamento_2 = None
        valor2_txt = ""

    obs = st.text_input("Observação", key=f"in_obs_{seq}")

    if st.button("➕ Adicionar Registro", type="primary", use_container_width=True):
        valor1 = converter_moeda(valor_txt)
        valor2 = converter_moeda(valor2_txt) if pag_misto else 0.0
        gorjetas = converter_moeda(gorjetas_txt)
        obs_limpa = str(obs).strip() if obs else ""

        if not local or not local.strip():
            st.warning("Preencha o campo Local / Descrição antes de adicionar.")
        elif valor1 is None or valor2 is None or gorjetas is None:
            st.error("Verifique os valores digitados. Use apenas números e vírgula ou ponto (Ex: 25,50).")
        elif (valor1 + valor2) == 0.0 and gorjetas == 0.0:
            st.warning("Informe um Valor ou uma Gorjeta antes de adicionar.")
        elif pag_misto and tipo_pagamento == tipo_pagamento_2:
            st.warning("Escolha formas de pagamento diferentes para o pagamento dividido.")
        else:
            valores_mapa = {
                "Dinheiro": 0.0,
                "PIX Bradesco": 0.0,
                "PIX Stones": 0.0,
                "Cartão": 0.0,
                "Despesas (Gasolina/Manut.)": 0.0
            }
            for col_n in lista_extras:
                valores_mapa[col_n] = 0.0

            valores_mapa[tipo_pagamento] += float(valor1)
            if pag_misto and tipo_pagamento_2:
                valores_mapa[tipo_pagamento_2] += float(valor2)

            dinheiro = float(valores_mapa["Dinheiro"])
            pix_brad = float(valores_mapa["PIX Bradesco"])
            pix_ston = float(valores_mapa["PIX Stones"])
            cartao = float(valores_mapa["Cartão"])
            despesas = float(valores_mapa["Despesas (Gasolina/Manut.)"])

            extras_dict = {col_n: float(valores_mapa[col_n]) for col_n in lista_extras}
            if despesas > 0:
                extras_dict["_origem_despesa"] = origem_despesa
            if gorjetas > 0:
                extras_dict["_forma_gorjeta"] = forma_gorjeta

            with st.spinner("Salvando na planilha..."):
                _ler_aba_cache.clear()
                df_atual = ler_aba("lancamentos")
                if not df_atual.empty:
                    df_atual_dia = df_atual[(df_atual["data_ref"] == data_str) & (df_atual["tipo"] == "CORRIDA") & (df_atual["usuario"] == usuario_atual)]
                else:
                    df_atual_dia = pd.DataFrame()
                
                num_corrida_atual = len(df_atual_dia) + 1
                agora = agora_br_str()
                novo_id = 1 if df_atual.empty else int(df_atual["id"].max()) + 1
                
                nova_linha = pd.DataFrame([{
                    "id": int(novo_id),
                    "data_ref": str(data_str),
                    "tipo": "CORRIDA",
                    "qtd": int(num_corrida_atual),
                    "local": str(local).strip(),
                    "dinheiro": dinheiro,
                    "pix_bradesco": pix_brad,
                    "pix_stones": pix_ston,
                    "cartao": cartao,
                    "gorjetas": float(gorjetas),
                    "despesas": despesas,
                    "obs": obs_limpa,
                    "extras": json.dumps(extras_dict, ensure_ascii=False),
                    "usuario": str(usuario_atual),
                    "data_hora": str(agora),
                    "usuario_alteracao": str(usuario_atual),
                    "data_alteracao": str(agora)
                }])
                df_atual = pd.concat([df_atual, nova_linha], ignore_index=True)
                salvar_aba("lancamentos", df_atual)

            st.session_state.form_seq += 1
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
        
        df_c["Forma Gorj."] = df_c.apply(
            lambda r: extrair_forma_gorjeta(r["extras"], r["dinheiro"]) if float(r["gorjetas"]) > 0 else "-",
            axis=1
        )
        df_c["Origem Desp."] = df_c.apply(
            lambda r: ("Dinheiro" if "Dinheiro" in extrair_origem_despesa(r["extras"]) else "Cartão/Conta") if float(r["despesas"]) > 0 else "-",
            axis=1
        )
        
        cols_soma = ["dinheiro", "pix_bradesco", "pix_stones", "cartao", "gorjetas"] + lista_extras
        df_c["Total Linha"] = df_c[cols_soma].sum(axis=1) - df_c["despesas"]
        
        df_exibir = df_c.rename(columns={"qtd": "Corrida Nº"})
        cols_show = ["id", "Corrida Nº", "local", "dinheiro", "pix_bradesco", "pix_stones", "cartao", "gorjetas", "Forma Gorj.", "despesas", "Origem Desp."] + lista_extras + ["Total Linha", "obs", "usuario", "data_hora", "usuario_alteracao", "data_alteracao"]
        st.dataframe(df_exibir[cols_show], use_container_width=True, hide_index=True)

        with st.expander("✏️ Alterar ou Excluir Registro"):
            id_edit = st.selectbox("Escolha o ID", df_c["id"].astype(int).tolist())
            idx_e = df_lanc[df_lanc["id"] == id_edit].index
            ed_loc = st.text_input("Local", value=str(df_lanc.loc[idx_e, "local"].iloc[0]), key=f"ed_loc_{id_edit}")
            ed_din_txt = st.text_input("Dinheiro", value=f"{float(df_lanc.loc[idx_e, 'dinheiro'].iloc[0]):.2f}".replace(".", ","), key=f"ed_din_{id_edit}")
            ed_brad_txt = st.text_input("PIX Bradesco", value=f"{float(df_lanc.loc[idx_e, 'pix_bradesco'].iloc[0]):.2f}".replace(".", ","), key=f"ed_brad_{id_edit}")
            ed_ston_txt = st.text_input("PIX Stones", value=f"{float(df_lanc.loc[idx_e, 'pix_stones'].iloc[0]):.2f}".replace(".", ","), key=f"ed_ston_{id_edit}")
            ed_cart_txt = st.text_input("Cartão", value=f"{float(df_lanc.loc[idx_e, 'cartao'].iloc[0]):.2f}".replace(".", ","), key=f"ed_cart_{id_edit}")
            ed_gorj_txt = st.text_input("Gorjetas", value=f"{float(df_lanc.loc[idx_e, 'gorjetas'].iloc[0]):.2f}".replace(".", ","), key=f"ed_gorj_{id_edit}")
            
            fgorj_atual = extrair_forma_gorjeta(df_lanc.loc[idx_e, "extras"].iloc[0], df_lanc.loc[idx_e, "dinheiro"].iloc[0])
            idx_fgorj = 0 if fgorj_atual == "Dinheiro" else 1
            ed_fgorj = st.radio(
                "Forma de Recebimento da Gorjeta (se houver)",
                ["Dinheiro", "PIX / Cartão"],
                index=idx_fgorj,
                horizontal=True,
                key=f"ed_fgorj_{id_edit}"
            )

            ed_desp_txt = st.text_input("Despesas", value=f"{float(df_lanc.loc[idx_e, 'despesas'].iloc[0]):.2f}".replace(".", ","), key=f"ed_desp_{id_edit}")
            
            orig_atual = extrair_origem_despesa(df_lanc.loc[idx_e, "extras"].iloc[0])
            idx_orig = 1 if "Dinheiro" in orig_atual else 0
            ed_orig_desp = st.radio(
                "Origem do Pagamento da Despesa (se houver)",
                ["Cartão / Conta (Não sai do caixa)", "Dinheiro do Caixa (Sai da gaveta/espécie)"],
                index=idx_orig,
                horizontal=True,
                key=f"ed_orig_{id_edit}"
            )
            obs_val = str(df_lanc.loc[idx_e, "obs"].iloc[0])
            ed_obs = st.text_input("Obs", value=obs_val, key=f"ed_obs_{id_edit}")

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
                    with st.spinner("Salvando alteração..."):
                        _ler_aba_cache.clear()
                        df_atual = ler_aba("lancamentos")
                        idx_e_atual = df_atual[df_atual["id"] == id_edit].index
                        agora = agora_br_str()
                        
                        try:
                            extras_atual = json.loads(str(df_atual.loc[idx_e_atual, "extras"].iloc[0]))
                        except Exception:
                            extras_atual = {}
                        
                        if float(ed_desp) > 0:
                            extras_atual["_origem_despesa"] = ed_orig_desp
                        else:
                            extras_atual.pop("_origem_despesa", None)

                        if float(ed_gorj) > 0:
                            extras_atual["_forma_gorjeta"] = ed_fgorj
                        else:
                            extras_atual.pop("_forma_gorjeta", None)

                        df_atual.loc[idx_e_atual, "local"] = str(ed_loc).strip()
                        df_atual.loc[idx_e_atual, "dinheiro"] = float(ed_din)
                        df_atual.loc[idx_e_atual, "pix_bradesco"] = float(ed_brad)
                        df_atual.loc[idx_e_atual, "pix_stones"] = float(ed_ston)
                        df_atual.loc[idx_e_atual, "cartao"] = float(ed_cart)
                        df_atual.loc[idx_e_atual, "gorjetas"] = float(ed_gorj)
                        df_atual.loc[idx_e_atual, "despesas"] = float(ed_desp)
                        df_atual.loc[idx_e_atual, "obs"] = str(ed_obs).strip()
                        df_atual.loc[idx_e_atual, "extras"] = json.dumps(extras_atual, ensure_ascii=False)
                        df_atual.loc[idx_e_atual, "usuario_alteracao"] = str(usuario_atual)
                        df_atual.loc[idx_e_atual, "data_alteracao"] = str(agora)
                        
                        salvar_aba("lancamentos", df_atual)
                    st.success("Alterado com sucesso!")
                    st.rerun()

            if st.button("🗑️ Excluir Registro", use_container_width=True):
                with st.spinner("Excluindo registro..."):
                    _ler_aba_cache.clear()
                    df_atual = ler_aba("lancamentos")
                    idx_e_atual = df_atual[df_atual["id"] == id_edit].index
                    dono_excluido = str(df_atual.loc[idx_e_atual, "usuario"].iloc[0])
                    df_atual = df_atual.drop(idx_e_atual)
                    mask_dia_corr = (df_atual["data_ref"] == data_str) & (df_atual["tipo"] == "CORRIDA") & (df_atual["usuario"] == dono_excluido)
                    df_atual.loc[mask_dia_corr, "qtd"] = range(1, mask_dia_corr.sum() + 1)
                    salvar_aba("lancamentos", df_atual)
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
    t_din_corr = df_c["dinheiro"].sum() if not df_c.empty else 0.0
    t_pix_corr = (df_c["pix_bradesco"].sum() + df_c["pix_stones"].sum() + df_c["cartao"].sum()) if not df_c.empty else 0.0
    t_corr = t_din_corr + t_pix_corr
    t_desp = df_c["despesas"].sum() if not df_c.empty else 0.0
    t_gorj = df_c["gorjetas"].sum() if not df_c.empty else 0.0

    if not df_c.empty:
        mask_gorj_din = df_c.apply(lambda r: extrair_forma_gorjeta(r["extras"], r["dinheiro"]) == "Dinheiro", axis=1)
        t_gorj_din = df_c.loc[mask_gorj_din, "gorjetas"].sum()
        t_gorj_dig = t_gorj - t_gorj_din

        mask_desp_din = df_c["extras"].apply(lambda x: "Dinheiro" in extrair_origem_despesa(x))
        t_desp_din = df_c.loc[mask_desp_din, "despesas"].sum()
        t_desp_cart = t_desp - t_desp_din
    else:
        t_gorj_din = 0.0
        t_gorj_dig = 0.0
        t_desp_din = 0.0
        t_desp_cart = 0.0

    t_din_total_gaveta = t_din_corr + t_gorj_din
    t_pix_total_conta = t_pix_corr + t_gorj_dig
    t_corr_com_gorj = t_corr + t_gorj

    st.metric("Total de Corridas Feitas no Dia", f"{total_corridas_feitas}")
    st.metric("1. Total em Dinheiro no Dia (Corridas + Gorjetas Dinheiro)", f"R$ {t_din_total_gaveta:.2f}")
    st.metric("2. Total PIX + Cartão (Corridas + Gorjetas Digitais)", f"R$ {t_pix_total_conta:.2f}")
    st.metric("3. Total Corridas com Gorjeta (Dinheiro + PIX + Cartão + Gorjeta)", f"R$ {t_corr_com_gorj:.2f}")
    st.metric("4. Total Corridas com Gorjeta - Diária", f"R$ {(t_corr_com_gorj - res_diaria):.2f}")
    st.metric("5. Total Caixa + Dinheiro (c/ Gorj. Din.) - Diária - Desp. Dinheiro", f"R$ {(res_caixa + t_din_total_gaveta - res_diaria - t_desp_din):.2f}")
    st.metric("6. Total Dinheiro (c/ Gorj. Din.) - Diária - Desp. Dinheiro (Acerto Espécie)", f"R$ {(t_din_total_gaveta - res_diaria - t_desp_din):.2f}")
    st.info(
        f"**Despesas:** R$ {t_desp:.2f} (Cartão/Conta: R$ {t_desp_cart:.2f} | Dinheiro: R$ {t_desp_din:.2f})  |  "
        f"**Gorjetas:** R$ {t_gorj:.2f} (Dinheiro: R$ {t_gorj_din:.2f} | PIX/Cartão: R$ {t_gorj_dig:.2f})"
    )
    st.success(f"**Lucro Líquido Real de Caixa (Corridas + Gorjetas - Diária - Desp. Dinheiro): R$ {(t_corr_com_gorj - res_diaria - t_desp_din):.2f}**")

elif opcao == "Relatórios e Gráficos":
    st.header("📈 Relatórios por Período")
    c_dt1, c_dt2 = st.columns(2)
    hoje_atual = hoje_br()
    dt_ini = c_dt1.date_input("Data Inicial", value=hoje_atual.replace(day=1))
    dt_fim = c_dt2.date_input("Data Final", value=hoje_atual)

    df_lanc = ler_aba("lancamentos")
    filtro_rel_user = usuario_atual
    if not df_lanc.empty:
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

        if not df_c.empty:
            mask_gorj_din = df_c.apply(lambda r: extrair_forma_gorjeta(r["extras"], r["dinheiro"]) == "Dinheiro", axis=1)
            tot_gorj_din = df_c.loc[mask_gorj_din, "gorjetas"].sum()
            tot_gorj_dig = tot_gorj - tot_gorj_din

            mask_desp_din = df_c["extras"].apply(lambda x: "Dinheiro" in extrair_origem_despesa(x))
            tot_desp_din = df_c.loc[mask_desp_din, "despesas"].sum()
            tot_desp_cart = tot_desp - tot_desp_din
        else:
            tot_gorj_din = 0.0
            tot_gorj_dig = 0.0
            tot_desp_din = 0.0
            tot_desp_cart = 0.0

        tot_din_com_gorj = tot_din + tot_gorj_din
        tot_pix_com_gorj = tot_pix_c + tot_gorj_dig

        res_operacional = tot_corr + tot_gorj - tot_diar
        lucro_real_caixa = tot_corr + tot_gorj - tot_diar - tot_desp_din

        c_m1, c_m2, c_m3 = st.columns(3)
        c_m1.metric("Total de Corridas no Período", f"{tot_qtd_corridas}")
        c_m2.metric("Faturamento Corridas", f"R$ {tot_corr:.2f}")
        c_m3.metric("Total Gorjetas (Din: R$ " + f"{tot_gorj_din:.2f}" + " | Dig: R$ " + f"{tot_gorj_dig:.2f})", f"R$ {tot_gorj:.2f}")

        c_m4, c_m5, c_m6 = st.columns(3)
        c_m4.metric("Total Dinheiro (c/ Gorj. Dinheiro)", f"R$ {tot_din_com_gorj:.2f}")
        c_m5.metric("Total PIX + Cartão (c/ Gorj. Digital)", f"R$ {tot_pix_com_gorj:.2f}")
        c_m6.metric("Total Diárias", f"R$ {tot_diar:.2f}")

        c_m7, c_m8, c_m9 = st.columns(3)
        c_m7.metric("Despesas Cartão/Conta (Informativo)", f"R$ {tot_desp_cart:.2f}")
        c_m8.metric("Despesas em Dinheiro (Sai do Caixa)", f"R$ {tot_desp_din:.2f}")
        c_m9.metric("Resultado Operacional (sem desp. cartão)", f"R$ {res_operacional:.2f}")

        st.success(f"**Lucro Líquido Real de Caixa (Entradas + Gorjetas - Diárias - Desp. Dinheiro): R$ {lucro_real_caixa:.2f}**")

        if not df_c.empty:
            val_din_pie = df_c["dinheiro"].sum()
            val_brad_pie = df_c["pix_bradesco"].sum()
            val_ston_pie = df_c["pix_stones"].sum()
            val_cart_pie = df_c["cartao"].sum()
            val_gorj_pie = df_c["gorjetas"].sum()
            soma_geral_pie = val_din_pie + val_brad_pie + val_ston_pie + val_cart_pie + val_gorj_pie

            fig_pie = px.pie(
                names=["Dinheiro", "PIX Bradesco", "PIX Stones", "Cartão", "Gorjetas"],
                values=[val_din_pie, val_brad_pie, val_ston_pie, val_cart_pie, val_gorj_pie],
                title=f"Entradas por Forma de Pagamento + Gorjetas (Total Geral: R$ {soma_geral_pie:,.2f})",
                hole=0.38
            )
            fig_pie.update_traces(
                texttemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>(%{percent})",
                textposition="inside"
            )
            fig_pie.add_annotation(
                text=f"<b>Total Geral</b><br>R$ {soma_geral_pie:,.2f}",
                x=0.5, y=0.5, font_size=14, showarrow=False
            )
            st.plotly_chart(fig_pie, use_container_width=True)

            df_c["Entradas (com Gorjetas)"] = df_c["dinheiro"] + df_c["pix_bradesco"] + df_c["pix_stones"] + df_c["cartao"] + df_c["gorjetas"]
            df_c["Desp. Dinheiro (Caixa)"] = df_c.apply(lambda r: float(r["despesas"]) if "Dinheiro" in extrair_origem_despesa(r["extras"]) else 0.0, axis=1)
            df_c["Desp. Cartão/Conta"] = df_c["despesas"] - df_c["Desp. Dinheiro (Caixa)"]

            df_agrup = df_c.groupby("data_ref")[["Entradas (com Gorjetas)", "Desp. Dinheiro (Caixa)", "Desp. Cartão/Conta"]].sum().reset_index()
            df_agrup = df_agrup.rename(columns={"data_ref": "Data"})
            fig_bar = px.bar(
                df_agrup, x="Data", y=["Entradas (com Gorjetas)", "Desp. Dinheiro (Caixa)", "Desp. Cartão/Conta"], barmode="group",
                title="Evolução Diária: Entradas x Despesas (Separadas por Origem)", labels={"value": "Valor (R$)", "variable": "Categoria"},
                text_auto=True
            )
            fig_bar.update_traces(texttemplate="R$ %{y:,.2f}", textposition="outside")
            fig_bar.update_layout(uniformtext_minsize=8, uniformtext_mode="show")
            st.plotly_chart(fig_bar, use_container_width=True)

            if eh_admin and filtro_rel_user == "Todos os Usuários":
                df_comp = df_c.groupby("usuario")[["Entradas (com Gorjetas)", "Desp. Dinheiro (Caixa)", "Desp. Cartão/Conta"]].sum().reset_index()
                df_comp = df_comp.rename(columns={"usuario": "Motorista"})
                fig_comp = px.bar(
                    df_comp, x="Motorista", y=["Entradas (com Gorjetas)", "Desp. Dinheiro (Caixa)", "Desp. Cartão/Conta"], barmode="group",
                    title="Comparativo por Usuário: Entradas x Despesas", labels={"value": "Valor (R$)", "variable": "Categoria"},
                    text_auto=True
                )
                fig_comp.update_traces(texttemplate="R$ %{y:,.2f}", textposition="outside")
                fig_comp.update_layout(uniformtext_minsize=8, uniformtext_mode="show")
                st.plotly_chart(fig_comp, use_container_width=True)

        metricas_pdf = {
            "qtd_corridas": tot_qtd_corridas,
            "tot_corr": tot_corr,
            "tot_din_com_gorj": tot_din_com_gorj,
            "tot_pix_com_gorj": tot_pix_com_gorj,
            "gorj_din": tot_gorj_din,
            "gorj_dig": tot_gorj_dig,
            "tot_gorj": tot_gorj,
            "tot_diar": tot_diar,
            "desp_caixa": tot_desp_din,
            "desp_cartao": tot_desp_cart,
            "tot_desp": tot_desp,
            "res_operacional": res_operacional,
            "lucro_real": lucro_real_caixa
        }
        pdf_bytes = gerar_pdf_relatorio(dt_ini, dt_fim, filtro_rel_user, metricas_pdf, df_c)

        c_dl1, c_dl2 = st.columns(2)
        c_dl1.download_button(
            "📄 Baixar Relatório Apresentável (PDF)",
            data=pdf_bytes,
            file_name=f"relatorio_fretes_{dt_ini}_{dt_fim}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )
        csv = df_p.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
        c_dl2.download_button(
            "📥 Baixar Planilha Bruta (CSV/Excel)",
            data=csv,
            file_name=f"relatorio_{dt_ini}_{dt_fim}.csv",
            mime="text/csv",
            use_container_width=True
        )

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
                _ler_aba_cache.clear()
                df_u = ler_aba("usuarios")
                novo_u = pd.DataFrame([{"username": u_log.strip(), "senha": str(u_sen).strip(), "nome": u_nom.strip(), "perfil": u_per}])
                salvar_aba("usuarios", pd.concat([df_u, novo_u], ignore_index=True))
                st.success("Usuário criado!")

    st.subheader("Adicionar Nova Coluna")
    with st.form("f_col", clear_on_submit=True):
        n_col = st.text_input("Nome da Coluna (Ex: Pedágio, Vale)")
        if st.form_submit_button("Adicionar Coluna"):
            if n_col:
                _ler_aba_cache.clear()
                df_cols = ler_aba("colunas_extras")
                nova_c = pd.DataFrame([{"nome_coluna": n_col.strip()}])
                salvar_aba("colunas_extras", pd.concat([df_cols, nova_c], ignore_index=True))
                st.success("Coluna criada!")
