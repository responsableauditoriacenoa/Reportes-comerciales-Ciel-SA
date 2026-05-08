from __future__ import annotations

from io import BytesIO
import re

import pandas as pd
import plotly.express as px
import streamlit as st

from config import CANONICAL_COLUMNS, DEFAULT_KEY_COLUMNS
import storage as db
import transform as tf

available_key_columns = tf.available_key_columns
default_txt_key_columns = tf.default_txt_key_columns
infer_column_mapping = tf.infer_column_mapping
normalize_dataframe = tf.normalize_dataframe
normalize_txt_dataframe = tf.normalize_txt_dataframe
read_cuenta_h_txt = getattr(tf, "read_cuenta_h_txt", lambda file: pd.DataFrame())
read_htm_margins = tf.read_htm_margins
read_excel = tf.read_excel
read_txt_table = tf.read_txt_table
read_subscription_file = getattr(tf, "read_subscription_file", read_txt_table)
normalize_subscriptions_dataframe = getattr(tf, "normalize_subscriptions_dataframe", lambda df: df)
default_subscription_key_columns = getattr(
    tf,
    "default_subscription_key_columns",
    lambda df: [column for column in df.columns if df[column].notna().any()][:3],
)

get_connection = db.get_connection
load_imports = db.load_imports
load_records = db.load_records
load_txt_imports = db.load_txt_imports
load_txt_records = db.load_txt_records
load_margin_records = getattr(db, "load_margin_records", lambda conn: pd.DataFrame())
load_cuenta_h_imports = getattr(db, "load_cuenta_h_imports", lambda conn: pd.DataFrame())
load_cuenta_h_records = getattr(db, "load_cuenta_h_records", lambda conn: pd.DataFrame())
load_subscription_imports = getattr(db, "load_subscription_imports", lambda conn: pd.DataFrame())
load_subscription_objectives = getattr(db, "load_subscription_objectives", lambda conn: pd.DataFrame())
load_subscription_records = getattr(db, "load_subscription_records", lambda conn: pd.DataFrame())
apply_txt_margins = db.apply_txt_margins
save_subscription_objective = getattr(db, "save_subscription_objective", None)
upsert_cuenta_h_records = getattr(db, "upsert_cuenta_h_records", None)
upsert_records = db.upsert_records
upsert_subscription_records = getattr(db, "upsert_subscription_records", None)
upsert_txt_records = db.upsert_txt_records


st.set_page_config(
    page_title="Reporting Patentamientos",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    apply_styles()

    conn = get_connection()
    records = load_records(conn)
    txt_records = load_txt_records(conn)
    margin_records = load_margin_records(conn)
    cuenta_h_records = load_cuenta_h_records(conn)
    subscription_records = load_subscription_records(conn)

    with st.sidebar:
        st.markdown("## Reporting")
        st.caption("Patentamientos y facturacion")
        st.markdown("<div class='sidebar-nav'>", unsafe_allow_html=True)
        section = st.radio(
            "Menu",
            ["KPIs", "Base de datos Comisiones Margenes", "Conciliacion cuenta H", "Suscripciones", "Historial"],
            label_visibility="collapsed",
        )
        st.markdown("</div>", unsafe_allow_html=True)
        st.divider()
        st.metric("Registros guardados", f"{len(records):,.0f}")
        st.metric("Registros TXT", f"{len(txt_records):,.0f}")
        st.metric("Movimientos H", f"{len(cuenta_h_records):,.0f}")
        st.metric("Suscripciones", f"{len(subscription_records):,.0f}")

    render_html(
        "<div class='page-hero'>"
        "<div>"
        "<p class='eyebrow'>Dashboard comercial</p>"
        "<h1>Reporting de Patentamientos y Facturacion</h1>"
        "<p class='hero-copy'>Seguimiento consolidado por fecha de matriculacion, marca y tipo de venta.</p>"
        "</div>"
        "</div>"
    )

    if section == "Base de datos Comisiones Margenes":
        render_txt_import(conn, txt_records, margin_records)
    elif section == "Conciliacion cuenta H":
        render_cuenta_h(conn, cuenta_h_records)
    elif section == "Suscripciones":
        render_subscriptions(conn, subscription_records)
    elif section == "KPIs":
        render_import(conn, compact=True)
        render_dashboard(records)
    else:
        render_history(conn)


def render_import(conn, compact: bool = False) -> None:
    with st.sidebar:
        with st.expander("Importacion Excel", expanded=True):
            uploaded_file = st.file_uploader(
                "Archivo Excel de ventas",
                type=["xlsx", "xls"],
                accept_multiple_files=False,
            )

    if uploaded_file is None:
        if not compact:
            st.info("Subi un Excel desde el panel lateral para detectar columnas y preparar la importacion.")
        return

    raw_df = read_excel(uploaded_file)
    if raw_df.empty:
        st.warning("El archivo no contiene filas para importar.")
        return

    raw_df.columns = [str(column).strip() for column in raw_df.columns]
    inferred = infer_column_mapping([_normalize_for_select(column) for column in raw_df.columns])
    normalized_options = {_normalize_for_select(column): column for column in raw_df.columns}

    st.subheader("Mapeo de columnas")
    st.caption("Ajusta el mapeo si el Excel usa nombres distintos.")

    mapping = {}
    cols = st.columns(3)
    for index, target in enumerate(CANONICAL_COLUMNS.keys()):
        with cols[index % 3]:
            normalized_default = inferred.get(target, "")
            options = [""] + list(normalized_options.keys())
            selected = st.selectbox(
                target.capitalize(),
                options=options,
                index=options.index(normalized_default) if normalized_default in options else 0,
                format_func=lambda item: "No mapear" if item == "" else normalized_options[item],
                key=f"map_{target}",
            )
            mapping[target] = selected

    preview_source = raw_df.rename(columns={column: _normalize_for_select(column) for column in raw_df.columns})
    normalized_df = normalize_dataframe(preview_source, mapping)
    key_candidates = available_key_columns(normalized_df)

    with st.sidebar:
        with st.expander("Opciones de importacion", expanded=True):
            key_columns = st.multiselect(
                "Columnas para detectar duplicados",
                options=list(normalized_df.columns),
                default=[column for column in DEFAULT_KEY_COLUMNS if column in key_candidates] or key_candidates,
            )
            import_clicked = st.button("Importar y actualizar base", type="primary", width="stretch")

    render_dataframe(normalized_df.head(50))

    if not key_columns:
        st.error("Elegi al menos una columna clave para poder solapar duplicados.")
        return

    if import_clicked:
        result = upsert_records(conn, normalized_df, uploaded_file.name, key_columns)
        st.success(
            "Importacion completa: "
            f"{result['inserted']} nuevas, {result['updated']} actualizadas, "
            f"{result['unchanged']} sin cambios."
        )


def render_dashboard(records: pd.DataFrame) -> None:
    if records.empty:
        st.info("Todavia no hay datos importados.")
        return

    df = records.copy()
    date_column = "fecha_matriculacion" if "fecha_matriculacion" in df.columns else "fecha"
    df[date_column] = pd.to_datetime(df[date_column], errors="coerce")
    invoice_date_column = first_existing_column(df, ["fec_fact", "fecha_factura", "fecha fact", "fecha"])
    df[invoice_date_column] = pd.to_datetime(df[invoice_date_column], errors="coerce")
    df["importe"] = pd.to_numeric(df["importe"], errors="coerce").fillna(0)

    min_date = df[date_column].min()
    max_date = df[date_column].max()
    with st.sidebar:
        with st.expander("Filtros del dashboard", expanded=True):
            if "marca" in df.columns:
                brands = sorted([brand for brand in df["marca"].dropna().astype(str).unique() if brand])
                selected_brands = st.multiselect("Marca", options=brands, default=brands)
                if selected_brands:
                    df = df[df["marca"].isin(selected_brands)]
            if "tipo_operacion" in df.columns:
                sale_types = sorted([item for item in df["tipo_operacion"].dropna().astype(str).unique() if item])
                selected_sale_types = st.multiselect("Tipo de venta", options=sale_types, default=sale_types)
                if selected_sale_types:
                    df = df[df["tipo_operacion"].isin(selected_sale_types)]
            if pd.notna(min_date) and pd.notna(max_date):
                selected_range = st.date_input("Rango de fecha de matriculacion", value=(min_date.date(), max_date.date()))
                if len(selected_range) == 2:
                    start, end = selected_range
                    df = df[(df[date_column].dt.date >= start) & (df[date_column].dt.date <= end)]

    patentamientos = df["matricula"].replace("", pd.NA).nunique()
    facturacion = df["importe"].sum()
    facturas = df["factura"].replace("", pd.NA).nunique()
    registros = len(df)
    ticket_promedio = facturacion / facturas if facturas else 0
    marcas = df["marca"].replace("", pd.NA).nunique() if "marca" in df.columns else 0
    plan_count = _unique_count_for(df, "tipo_operacion", "Plan de ahorro")
    conventional_count = _unique_count_for(df, "tipo_operacion", "Venta convencional")
    peugeot_count = _unique_count_for(df, "marca", "Peugeot")
    citroen_count = _unique_count_for(df, "marca", "Citroen")

    render_kpi_grid(
        [
            ("Patentamientos", _format_number(patentamientos), "Matriculas unicas", "primary"),
            ("Facturacion", _format_currency(facturacion), "Total consolidado", "sky"),
            ("Facturas", _format_number(facturas), "Referencias unicas", "indigo"),
            ("Ticket promedio", _format_currency(ticket_promedio), "Facturacion / facturas", "cyan"),
            ("Peugeot", _format_number(peugeot_count), "Patentamientos", "primary"),
            ("Citroen", _format_number(citroen_count), "Patentamientos", "sky"),
            ("Plan de ahorro", _format_number(plan_count), "T.venta = 5", "indigo"),
            ("Convencional", _format_number(conventional_count), "Resto de operaciones", "cyan"),
        ]
    )

    render_html(
        "<div class='summary-strip'>"
        f"<div><span>Registros filtrados</span><strong>{_format_number(registros)}</strong></div>"
        f"<div><span>Marcas activas</span><strong>{_format_number(marcas)}</strong></div>"
        f"<div><span>Desde</span><strong>{min_date.strftime('%d/%m/%Y') if pd.notna(min_date) else '-'}</strong></div>"
        f"<div><span>Hasta</span><strong>{max_date.strftime('%d/%m/%Y') if pd.notna(max_date) else '-'}</strong></div>"
        "</div>"
    )

    monthly = (
        df.dropna(subset=[date_column])
        .assign(periodo=lambda data: data[date_column].dt.to_period("M").astype(str))
        .groupby("periodo", as_index=False)
        .agg(
            patentamientos=("matricula", lambda values: values.replace("", pd.NA).nunique()),
        )
    )
    monthly_billing = (
        df.dropna(subset=[invoice_date_column])
        .assign(periodo=lambda data: data[invoice_date_column].dt.to_period("M").astype(str))
        .groupby("periodo", as_index=False)
        .agg(facturacion=("importe", "sum"))
    )
    if not monthly.empty:
        monthly["periodo_label"] = pd.to_datetime(monthly["periodo"] + "-01").dt.strftime("%b %Y")
    if not monthly_billing.empty:
        monthly_billing["periodo_label"] = pd.to_datetime(monthly_billing["periodo"] + "-01").dt.strftime("%b %Y")

    if not monthly.empty or not monthly_billing.empty:
        left, right = st.columns(2)
        if not monthly.empty:
            monthly_bar = px.bar(
                monthly,
                x="periodo_label",
                y="patentamientos",
                title="Patentamientos por mes de matriculacion",
                text="patentamientos",
                color_discrete_sequence=["#2563eb"],
            )
            monthly_bar.update_traces(marker_line_color="#1e40af", marker_line_width=1.2, textposition="outside")
            style_chart(monthly_bar, x_title="Mes de matriculacion", y_title="Patentamientos")
            monthly_bar.update_xaxes(type="category")
            left.plotly_chart(monthly_bar, width="stretch")

        if not monthly_billing.empty:
            monthly_line = px.area(
                monthly_billing,
                x="periodo_label",
                y="facturacion",
                title="Facturacion por mes",
                markers=True,
                color_discrete_sequence=["#0ea5e9"],
            )
            monthly_line.update_traces(line_width=3, marker_size=8, fillcolor="rgba(14, 165, 233, 0.18)")
            style_chart(monthly_line, x_title="Mes de factura", y_title="Facturacion")
            monthly_line.update_xaxes(type="category")
            right.plotly_chart(monthly_line, width="stretch")

    left, right = st.columns(2)

    if "marca" in df.columns:
        by_brand = (
            df[df["marca"].fillna("").astype(str).str.len() > 0]
            .groupby("marca", as_index=False)
            .agg(
                patentamientos=("matricula", lambda values: values.replace("", pd.NA).nunique()),
                facturacion=("importe", "sum"),
            )
            .sort_values("patentamientos", ascending=False)
        )
        if not by_brand.empty:
            brand_chart = px.bar(
                by_brand,
                x="marca",
                y="patentamientos",
                title="Patentamientos por marca",
                text="patentamientos",
                color="marca",
                color_discrete_map={"Peugeot": "#2563eb", "Citroen": "#0ea5e9"},
            )
            brand_chart.update_traces(marker_line_color="#ffffff", marker_line_width=1.5, textposition="outside")
            style_chart(brand_chart, y_title="Patentamientos", show_legend=False)
            left.plotly_chart(
                brand_chart,
                width="stretch",
            )

    if "tipo_operacion" in df.columns:
        by_sale_type = (
            df[df["tipo_operacion"].fillna("").astype(str).str.len() > 0]
            .groupby("tipo_operacion", as_index=False)
            .agg(
                patentamientos=("matricula", lambda values: values.replace("", pd.NA).nunique()),
                facturacion=("importe", "sum"),
            )
            .sort_values("patentamientos", ascending=False)
        )
        if not by_sale_type.empty:
            sale_chart = px.pie(
                by_sale_type,
                names="tipo_operacion",
                values="patentamientos",
                title="Mix de patentamientos por tipo de venta",
                hole=0.58,
                color="tipo_operacion",
                color_discrete_map={"Plan de ahorro": "#2563eb", "Venta convencional": "#06b6d4"},
            )
            sale_chart.update_traces(textinfo="label+percent+value", marker_line_color="#ffffff", marker_line_width=3)
            style_chart(sale_chart, height=390)
            right.plotly_chart(
                sale_chart,
                width="stretch",
            )

    if "producto" in df.columns:
        by_product = (
            df[df["producto"].fillna("").astype(str).str.len() > 0]
            .groupby("producto", as_index=False)
            .agg(
                patentamientos=("matricula", lambda values: values.replace("", pd.NA).nunique()),
                facturacion=("importe", "sum"),
            )
            .sort_values("patentamientos", ascending=False)
            .head(15)
        )
        if not by_product.empty:
            product_chart = px.bar(
                by_product.sort_values("patentamientos", ascending=True),
                x="patentamientos",
                y="producto",
                orientation="h",
                title="Top productos/modelos por patentamientos",
                text="patentamientos",
                color="patentamientos",
                color_continuous_scale=["#dbeafe", "#2563eb", "#0f3f8c"],
            )
            product_chart.update_traces(marker_line_color="#ffffff", marker_line_width=1.2, textposition="outside")
            style_chart(product_chart, x_title="Patentamientos", y_title="", show_coloraxis=False, height=520)
            st.plotly_chart(
                product_chart,
                width="stretch",
            )


def render_txt_import(conn, existing_records: pd.DataFrame, margin_records: pd.DataFrame) -> None:
    with st.sidebar:
        with st.expander("Importacion TXT", expanded=True):
            uploaded_file = st.file_uploader(
                "Archivo TXT",
                type=["txt", "csv"],
                accept_multiple_files=False,
                key="txt_uploader",
            )
        with st.expander("Margenes HTM", expanded=False):
            margin_file = st.file_uploader(
                "Archivo HTM de margenes",
                type=["htm", "html"],
                accept_multiple_files=False,
                key="htm_margin_uploader",
            )

    if margin_file is not None:
        render_margin_import(conn, margin_file)
        existing_records = load_txt_records(conn)
        margin_records = load_margin_records(conn)

    if uploaded_file is None:
        st.info("Subi un TXT desde el panel lateral para convertirlo en tabla y consolidarlo historicamente.")
        if not existing_records.empty:
            st.subheader("Base TXT consolidada")
            render_txt_table(existing_records, margin_records)
        elif not margin_records.empty:
            render_margin_kpis(existing_records, margin_records)
        return

    raw_df = read_txt_table(uploaded_file)
    normalized_df = normalize_txt_dataframe(raw_df)
    importable_df = _filter_plan_savings_rows(normalized_df)

    st.subheader("Preview TXT")
    st.caption("Solo se guardan operaciones del canal Plan de ahorro. El resto de los canales se ignora al importar.")
    render_dataframe(importable_df.head(80))

    with st.sidebar:
        with st.expander("Opciones TXT", expanded=True):
            default_keys = default_txt_key_columns(importable_df)
            key_columns = st.multiselect(
                "Columnas para detectar duplicados",
                options=list(importable_df.columns),
                default=default_keys,
                key="txt_key_columns",
            )
            import_clicked = st.button("Importar TXT y actualizar base", type="primary", width="stretch")

    if importable_df.empty:
        st.warning("No encontre operaciones de Plan de ahorro en este archivo.")
        return

    if not key_columns:
        st.error("Elegi al menos una columna clave. Para este TXT recomiendo Pedido ABCnet.")
        return

    if import_clicked:
        result = upsert_txt_records(conn, importable_df, uploaded_file.name, key_columns)
        ignored_by_channel = len(normalized_df) - len(importable_df) + result.get("skipped", 0)
        st.success(
            "Importacion TXT completa: "
            f"{result['inserted']} nuevas, {result['updated']} actualizadas, "
            f"{result['unchanged']} sin cambios, {ignored_by_channel} ignoradas por canal."
        )
        existing_records = load_txt_records(conn)

    if not existing_records.empty:
        st.subheader("Base TXT consolidada")
        render_txt_table(existing_records, margin_records)


def render_margin_import(conn, margin_file) -> None:
    margins_df = read_htm_margins(margin_file)
    st.subheader("Preview margenes HTM")

    if margins_df.empty:
        st.warning("No pude encontrar filas de margen con Concepto, Contrato e Importe en el HTM.")
        return

    st.caption("El cruce se realiza tomando los primeros 4 caracteres del contrato como Grupo y los 3 siguientes como Orden.")
    render_dataframe(margins_df.head(50))

    if st.button("Aplicar margenes a base TXT", type="primary", width="stretch"):
        result = apply_txt_margins(conn, margins_df, margin_file.name)
        st.success(
            "Margenes aplicados: "
            f"{result['stored_margins']} conceptos guardados, "
            f"{result['updated']} filas actualizadas, {result['matched_margins']} conceptos vinculados, "
            f"{result['unchanged']} sin cambios, "
            f"{result['unmatched']} conceptos sin coincidencia."
        )


def render_txt_table(df: pd.DataFrame, margin_records: pd.DataFrame | None = None) -> None:
    search = st.text_input("Buscar en base TXT", key="txt_search")
    view = order_txt_by_approval_date(order_txt_columns(_deduplicate_txt_view(df)))
    if search:
        mask = view.astype(str).apply(lambda column: column.str.contains(search, case=False, na=False)).any(axis=1)
        view = view[mask]

    render_dataframe(view)
    st.download_button(
        "Descargar base TXT consolidada",
        data=view.to_csv(index=False).encode("utf-8-sig"),
        file_name="base_txt_consolidada.csv",
        mime="text/csv",
        width="stretch",
    )
    st.download_button(
        "Descargar base TXT consolidada Excel",
        data=to_excel_bytes(view, sheet_name="Base TXT"),
        file_name="base_txt_consolidada.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
    render_txt_kpis(view, margin_records)


def render_cuenta_h(conn, existing_records: pd.DataFrame) -> None:
    with st.sidebar:
        with st.expander("Importacion Cuenta H", expanded=True):
            uploaded_file = st.file_uploader(
                "Archivo TXT cuenta H",
                type=["txt"],
                accept_multiple_files=False,
                key="cuenta_h_uploader",
            )

    if uploaded_file is not None:
        parsed_df = read_cuenta_h_txt(uploaded_file)
        st.subheader("Preview conciliacion cuenta H")
        if parsed_df.empty:
            st.warning("No encontre movimientos de cuenta H en el TXT.")
        else:
            st.caption("Se importan movimientos reales de GL H y se excluyen encabezados/totales.")
            render_dataframe(order_cuenta_h_columns(parsed_df).head(80))
            if st.button("Importar conciliacion cuenta H", type="primary", width="stretch"):
                if upsert_cuenta_h_records is None:
                    st.error("La base de datos todavia no tiene habilitado el modulo Cuenta H. Reinicia la app y vuelve a intentar.")
                    return
                result = upsert_cuenta_h_records(
                    conn,
                    parsed_df,
                    uploaded_file.name,
                    ["Cuenta", "GL", "N.Doc.", "Tipo", "F.Comp."],
                )
                st.success(
                    "Importacion cuenta H completa: "
                    f"{result['inserted']} nuevas, {result['updated']} actualizadas, "
                    f"{result['unchanged']} sin cambios."
                )
                existing_records = load_cuenta_h_records(conn)

    st.subheader("Conciliacion cuenta H")
    if existing_records.empty:
        st.info("Subi un TXT de cuenta H desde el panel lateral para crear la base consolidada.")
        return

    render_cuenta_h_table(existing_records)


def render_cuenta_h_table(df: pd.DataFrame) -> None:
    with st.sidebar:
        with st.expander("Filtros Cuenta H", expanded=True):
            concepts = sorted([item for item in df.get("Concepto", pd.Series(dtype=object)).dropna().astype(str).unique() if item])
            selected_concepts = st.multiselect("Concepto", options=concepts, default=concepts)
            search = st.text_input("Buscar movimiento H")

    view = order_cuenta_h_columns(df.copy())
    if selected_concepts and "Concepto" in view.columns:
        view = view[view["Concepto"].isin(selected_concepts)]
    if search:
        mask = view.astype(str).apply(lambda column: column.str.contains(search, case=False, na=False)).any(axis=1)
        view = view[mask]

    render_cuenta_h_kpis(view)
    render_dataframe(view)

    col1, col2 = st.columns(2)
    col1.download_button(
        "Descargar conciliacion H CSV",
        data=view.to_csv(index=False).encode("utf-8-sig"),
        file_name="conciliacion_cuenta_h.csv",
        mime="text/csv",
        width="stretch",
    )
    col2.download_button(
        "Descargar conciliacion H Excel",
        data=to_excel_bytes(view, sheet_name="Cuenta H"),
        file_name="conciliacion_cuenta_h.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )


def render_cuenta_h_kpis(df: pd.DataFrame) -> None:
    debito = pd.to_numeric(df.get("Debito", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
    credito = pd.to_numeric(df.get("Credito", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
    saldo = credito - debito
    render_kpi_grid(
        [
            ("Movimientos H", _format_number(len(df)), "Base consolidada filtrada", "primary"),
            ("Debitos", _format_currency(debito), "Total debe", "indigo"),
            ("Creditos", _format_currency(credito), "Total haber", "sky"),
            ("Saldo neto", _format_currency(saldo), "Creditos - debitos", "cyan"),
        ]
    )

    if "Concepto" not in df.columns:
        return
    by_concept = (
        df.assign(Debito=pd.to_numeric(df["Debito"], errors="coerce").fillna(0), Credito=pd.to_numeric(df["Credito"], errors="coerce").fillna(0))
        .groupby("Concepto", as_index=False)
        .agg(debito=("Debito", "sum"), credito=("Credito", "sum"), movimientos=("Concepto", "size"))
    )
    if by_concept.empty:
        return
    by_concept["saldo"] = by_concept["credito"] - by_concept["debito"]
    chart = px.bar(
        by_concept.sort_values("saldo", ascending=True),
        x="saldo",
        y="Concepto",
        orientation="h",
        title="Saldo por concepto cuenta H",
        text="saldo",
        color="saldo",
        color_continuous_scale=["#ef4444", "#dbeafe", "#2563eb"],
    )
    chart.update_traces(texttemplate="$%{text:,.0f}", textposition="outside", marker_line_color="#ffffff", marker_line_width=1.2)
    style_chart(chart, x_title="Saldo", y_title="", show_coloraxis=False, height=520)
    st.plotly_chart(chart, width="stretch")


def render_subscriptions(conn, existing_records: pd.DataFrame) -> None:
    objectives = load_subscription_objectives(conn)
    with st.sidebar:
        with st.expander("Importacion Suscripciones", expanded=True):
            uploaded_file = st.file_uploader(
                "Archivo Suscripciones",
                type=["xlsx", "xls", "csv", "txt"],
                accept_multiple_files=False,
                key="subscriptions_uploader",
            )
        with st.expander("Objetivo mensual", expanded=True):
            current_year = int(pd.Timestamp.today().year)
            objective_year = st.selectbox("Año objetivo", list(range(current_year - 3, current_year + 2)), index=3, key="subscription_objective_year")
            objective_month = st.selectbox(
                "Mes objetivo",
                options=list(range(1, 13)),
                index=int(pd.Timestamp.today().month) - 1,
                format_func=lambda month: month_name_es(month),
                key="subscription_objective_month",
            )
            objective_value = st.number_input("Objetivo", min_value=0, step=1, key="subscription_objective_value")
            save_objective = st.button("Guardar objetivo", type="primary", width="stretch")

    if save_objective:
        if save_subscription_objective is None:
            st.error("El modulo de objetivos todavia no esta disponible en la base. Reinicia la app y vuelve a intentar.")
        else:
            periodo = f"{objective_year}-{int(objective_month):02d}"
            save_subscription_objective(conn, periodo, int(objective_value))
            st.success(f"Objetivo guardado para {periodo}: {int(objective_value):,.0f}")
            objectives = load_subscription_objectives(conn)

    if uploaded_file is not None:
        raw_df = read_subscription_file(uploaded_file)
        normalized_df = normalize_subscriptions_dataframe(raw_df)
        st.subheader("Preview Suscripciones")
        render_dataframe(normalized_df.head(80))

        with st.sidebar:
            with st.expander("Opciones Suscripciones", expanded=True):
                key_columns = st.multiselect(
                    "Columnas para detectar duplicados",
                    options=list(normalized_df.columns),
                    default=default_subscription_key_columns(normalized_df),
                    key="subscription_key_columns",
                )
                import_clicked = st.button("Importar suscripciones", type="primary", width="stretch")

        if import_clicked:
            if upsert_subscription_records is None:
                st.error("El modulo Suscripciones todavia no esta disponible en la base. Reinicia la app y vuelve a intentar.")
            elif not key_columns:
                st.error("Elegi al menos una columna clave.")
            else:
                result = upsert_subscription_records(conn, normalized_df, uploaded_file.name, key_columns)
                st.success(
                    "Importacion suscripciones completa: "
                    f"{result['inserted']} nuevas, {result['updated']} actualizadas, "
                    f"{result['unchanged']} sin cambios."
                )
                existing_records = load_subscription_records(conn)

    st.subheader("Suscripciones")
    if existing_records.empty:
        st.info("Subi un archivo de suscripciones desde el panel lateral para crear la base consolidada.")
        if not objectives.empty:
            st.subheader("Objetivos cargados")
            render_dataframe(objectives)
        return

    render_subscriptions_dashboard(existing_records, objectives)


def render_subscriptions_dashboard(df: pd.DataFrame, objectives: pd.DataFrame) -> None:
    view = df.copy()
    view["fecha_ingreso"] = pd.to_datetime(view["fecha_ingreso"], errors="coerce")
    available_periods = sorted(view.dropna(subset=["fecha_ingreso"])["fecha_ingreso"].dt.to_period("M").astype(str).unique(), reverse=True)
    selected_period = available_periods[0] if available_periods else pd.Timestamp.today().to_period("M").strftime("%Y-%m")

    with st.sidebar:
        with st.expander("Filtros Suscripciones", expanded=True):
            period_years = sorted({int(period[:4]) for period in available_periods} or {int(pd.Timestamp.today().year)}, reverse=True)
            selected_year = st.selectbox("Año ingreso", period_years, key="subscription_filter_year")
            available_months = sorted(
                [int(period[5:7]) for period in available_periods if int(period[:4]) == selected_year]
                or [int(pd.Timestamp.today().month)]
            )
            selected_month = st.selectbox(
                "Mes ingreso",
                available_months,
                index=len(available_months) - 1,
                format_func=lambda month: month_name_es(month),
                key="subscription_filter_month",
            )
            selected_period = f"{selected_year}-{int(selected_month):02d}"
            view = view[view["fecha_ingreso"].dt.to_period("M").astype(str) == selected_period]
            brands = sorted([item for item in view["marca"].dropna().astype(str).unique() if item])
            selected_brands = st.multiselect("Marca", brands, default=brands, key="subscription_brand_filter")
            if selected_brands:
                view = view[view["marca"].isin(selected_brands)]

    by_month = view.dropna(subset=["fecha_ingreso"]).assign(periodo=lambda data: data["fecha_ingreso"].dt.to_period("M").astype(str))
    objective_total = 0
    if not objectives.empty:
        objective_total = objectives[objectives["periodo"] == selected_period]["objetivo"].sum()
    compliance = (len(view) / objective_total * 100) if objective_total else 0

    peugeot_count = count_brand_subscriptions(view, "Peugeot")
    citroen_count = count_brand_subscriptions(view, "Citroen")

    render_kpi_grid(
        [
            ("Suscripciones", _format_number(len(view)), f"Ingreso {selected_period}", "primary"),
            ("Peugeot", _format_number(peugeot_count), "Suscripciones filtradas", "sky"),
            ("Citroen", _format_number(citroen_count), "Suscripciones filtradas", "indigo"),
            ("Objetivo", _format_number(objective_total), f"Objetivo {selected_period}", "cyan"),
            ("% Cumplimiento", f"{compliance:,.1f}%", "Suscripciones / objetivo", "indigo"),
            ("Vendedores", _format_number(view["vendedor"].replace("", pd.NA).nunique()), "Activos en filtro", "cyan"),
        ]
    )

    col1, col2 = st.columns(2)
    by_brand = view.groupby("marca", as_index=False).size().rename(columns={"size": "suscripciones"})
    if not by_brand.empty:
        brand_chart = px.bar(by_brand, x="marca", y="suscripciones", text="suscripciones", title="Q de suscripciones por marca")
        brand_chart.update_traces(textposition="outside", marker_color="#2563eb")
        style_chart(brand_chart, x_title="Marca", y_title="Suscripciones", show_legend=False)
        col1.plotly_chart(brand_chart, width="stretch")

    by_seller = view.groupby("vendedor", as_index=False).size().rename(columns={"size": "suscripciones"}).sort_values("suscripciones", ascending=True)
    if not by_seller.empty:
        seller_chart = px.bar(by_seller, x="suscripciones", y="vendedor", orientation="h", text="suscripciones", title="Q de suscripciones por vendedor")
        seller_chart.update_traces(textposition="outside", marker_color="#0ea5e9")
        style_chart(seller_chart, x_title="Suscripciones", y_title="", show_legend=False, height=480)
        col2.plotly_chart(seller_chart, width="stretch")

    full_view = df.copy()
    full_view["fecha_ingreso"] = pd.to_datetime(full_view["fecha_ingreso"], errors="coerce")
    if selected_brands:
        full_view = full_view[full_view["marca"].isin(selected_brands)]
    trend = (
        full_view.dropna(subset=["fecha_ingreso"])
        .assign(periodo=lambda data: data["fecha_ingreso"].dt.to_period("M").astype(str))
        .groupby("periodo", as_index=False)
        .size()
        .rename(columns={"size": "suscripciones"})
    )
    if not trend.empty:
        trend["periodo_label"] = pd.to_datetime(trend["periodo"] + "-01").dt.strftime("%b %Y")
        trend_chart = px.line(trend, x="periodo_label", y="suscripciones", markers=True, text="suscripciones", title="Tendencia por mes de fecha de ingreso")
        trend_chart.update_traces(line_width=4, marker_size=10, textposition="top center")
        style_chart(trend_chart, x_title="Mes de ingreso", y_title="Suscripciones")
        trend_chart.update_xaxes(type="category")
        st.plotly_chart(trend_chart, width="stretch")

    st.subheader("Base suscripciones consolidada")
    render_dataframe(view)
    c1, c2 = st.columns(2)
    c1.download_button("Descargar suscripciones CSV", view.to_csv(index=False).encode("utf-8-sig"), "suscripciones.csv", "text/csv", width="stretch")
    c2.download_button("Descargar suscripciones Excel", to_excel_bytes(view, "Suscripciones"), "suscripciones.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")


def order_cuenta_h_columns(df: pd.DataFrame) -> pd.DataFrame:
    preferred = [
        "Concepto",
        "Texto",
        "Cuenta",
        "GL",
        "N.Doc.",
        "Tipo",
        "N.Fac",
        "Debito",
        "Credito",
        "Saldo",
        "F.Comp.",
        "F.Valor",
        "F.Venc.",
        "Debito U$",
        "Credito U$",
    ]
    ordered = [column for column in preferred if column in df.columns]
    rest = [column for column in df.columns if column not in ordered]
    return df[ordered + rest]


def order_txt_columns(df: pd.DataFrame) -> pd.DataFrame:
    margin_columns = [
        "Margen total",
        "Margen Cambio Modelo Contado",
        "Margen Venta 1ra parte",
        "Margen Venta 2da parte",
        "Contrato margen",
        "Concepto margen",
        "Importe margen",
        "Fecha margen",
        "Suscripcion margen",
        "Cuota margen",
        "Archivo margen",
    ]
    visible_margin_columns = [column for column in margin_columns if column in df.columns]
    if not visible_margin_columns:
        return df

    base_columns = [column for column in df.columns if column not in visible_margin_columns]
    insert_after = "Orden" if "Orden" in base_columns else "Grupo" if "Grupo" in base_columns else None
    if insert_after is None:
        return df[visible_margin_columns + base_columns]

    insert_position = base_columns.index(insert_after) + 1
    ordered = base_columns[:insert_position] + visible_margin_columns + base_columns[insert_position:]
    return df[ordered]


def order_txt_by_approval_date(df: pd.DataFrame) -> pd.DataFrame:
    if "Fecha Aprobacion" not in df.columns:
        return df

    sorted_df = df.copy()
    sorted_df["_fecha_aprobacion_sort"] = pd.to_datetime(
        sorted_df["Fecha Aprobacion"],
        errors="coerce",
    )
    sorted_df = sorted_df.sort_values(
        by=["_fecha_aprobacion_sort", "Nro.Orden" if "Nro.Orden" in sorted_df.columns else "_fecha_aprobacion_sort"],
        ascending=[False, False],
        na_position="last",
    )
    return sorted_df.drop(columns=["_fecha_aprobacion_sort"])


def render_txt_kpis(df: pd.DataFrame, margin_records: pd.DataFrame | None = None) -> None:
    if df.empty:
        return

    st.subheader("KPIs TXT")

    unit_column = "Nro.Orden" if "Nro.Orden" in df.columns else None
    invoice_column = "Nro.Factura" if "Nro.Factura" in df.columns else None
    channel_column = "Canal Vta." if "Canal Vta." in df.columns else None

    total_units = _count_units(df, unit_column)
    invoiced_units = _count_units(df[_not_empty(df[invoice_column])] if invoice_column else df.iloc[0:0], unit_column)

    plan_df = df.iloc[0:0]
    if channel_column:
        plan_df = df[df[channel_column].fillna("").astype(str).str.contains("plan", case=False, na=False)]
    plan_units = _count_units(plan_df, unit_column)
    plan_invoiced = _count_units(plan_df[_not_empty(plan_df[invoice_column])] if invoice_column else plan_df.iloc[0:0], unit_column)
    plan_pending = max(plan_units - plan_invoiced, 0)

    render_kpi_grid(
        [
            ("Unidades TXT", _format_number(total_units), "Base consolidada filtrada", "primary"),
            ("Con factura", _format_number(invoiced_units), "Nro.Factura informado", "sky"),
            ("Plan de ahorro", _format_number(plan_units), "Canal Vta. plan", "indigo"),
            ("Plan con factura", _format_number(plan_invoiced), "Planes con Nro.Factura", "cyan"),
            ("Plan sin factura", _format_number(plan_pending), "Pendientes de facturar", "indigo"),
        ]
    )

    render_margin_kpis(df, margin_records)

    if "Fecha Aprobacion" in df.columns:
        approved_df = df.copy()
        approved_df["Fecha Aprobacion"] = pd.to_datetime(approved_df["Fecha Aprobacion"], errors="coerce")
        approved_df = approved_df.dropna(subset=["Fecha Aprobacion"])

        if not approved_df.empty:
            pedido_column = "Pedido ABCnet" if "Pedido ABCnet" in approved_df.columns else unit_column
            if pedido_column:
                approved_df["_pedido"] = approved_df[pedido_column].fillna("").astype(str).str.strip()
                approved_df = approved_df[approved_df["_pedido"] != ""]
            else:
                approved_df["_pedido"] = approved_df.index.astype(str)

            monthly_approved = (
                approved_df.assign(periodo=lambda data: data["Fecha Aprobacion"].dt.to_period("M").astype(str))
                .groupby("periodo", as_index=False)
                .agg(pedidos_aprobados=("_pedido", "nunique"))
                .sort_values("periodo")
            )
            monthly_approved["periodo_label"] = pd.to_datetime(monthly_approved["periodo"] + "-01").dt.strftime("%b %Y")

            approved_chart = px.bar(
                monthly_approved,
                x="periodo_label",
                y="pedidos_aprobados",
                title="Cantidad de pedidos aprobados por mes",
                text="pedidos_aprobados",
                color="pedidos_aprobados",
                color_continuous_scale=["#dbeafe", "#2563eb", "#0f3f8c"],
            )
            approved_chart.update_traces(marker_line_color="#ffffff", marker_line_width=1.4, textposition="outside")
            style_chart(approved_chart, x_title="Mes de aprobacion", y_title="Pedidos aprobados", show_coloraxis=False)
            approved_chart.update_xaxes(type="category")
            st.plotly_chart(approved_chart, width="stretch")


def render_margin_kpis(df: pd.DataFrame, margin_records: pd.DataFrame | None = None) -> None:
    source_df = margin_records.copy() if margin_records is not None and not margin_records.empty else df.copy()
    amount_column = "Importe margen" if "Importe margen" in source_df.columns else "Margen total"
    if amount_column not in source_df.columns:
        return

    margin_df = source_df.copy()
    margin_df[amount_column] = pd.to_numeric(margin_df[amount_column], errors="coerce")
    margin_df = margin_df[margin_df[amount_column].notna() & (margin_df[amount_column] != 0)]
    if margin_df.empty:
        return

    margin_total = margin_df[amount_column].sum()
    margin_units = _count_units(margin_df, "Contrato margen" if "Contrato margen" in margin_df.columns else "Nro.Orden" if "Nro.Orden" in margin_df.columns else None)

    unmatched_margins = 0
    if margin_records is not None and not margin_records.empty and not df.empty:
        txt_keys = set(
            zip(
                df.get("Grupo", pd.Series(dtype=object)).astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4),
                df.get("Orden", pd.Series(dtype=object)).astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(3),
            )
        )
        margin_keys = list(
            zip(
                margin_df.get("Grupo margen", pd.Series(dtype=object)).astype(str).str.zfill(4),
                margin_df.get("Orden margen", pd.Series(dtype=object)).astype(str).str.zfill(3),
            )
        )
        unmatched_margins = sum(1 for key in margin_keys if key not in txt_keys)

    render_kpi_grid(
        [
            ("Sumatoria de margenes", _format_currency(margin_total), "Importe margen total", "primary"),
            ("Contratos con margen", _format_number(margin_units), "Incluye no encontrados en TXT", "sky"),
            ("Margenes sin base TXT", _format_number(unmatched_margins), "Conceptos sin Grupo + Orden en base", "indigo"),
        ]
    )

    concept_cards = []
    accents = ["primary", "sky", "indigo", "cyan"]
    if "Concepto margen" in margin_df.columns:
        by_concept = (
            margin_df.groupby("Concepto margen", as_index=False)
            .agg(total_margen=(amount_column, "sum"), conceptos=(amount_column, "size"))
            .sort_values("total_margen", ascending=False)
        )
        for index, row in by_concept.iterrows():
            concept_cards.append(
                (
                    str(row["Concepto margen"]),
                    _format_currency(row["total_margen"]),
                    f"{_format_number(row['conceptos'])} conceptos",
                    accents[index % len(accents)],
                )
            )

    if concept_cards:
        st.markdown("#### Margen por concepto")
        render_kpi_grid(concept_cards)

    if "Fecha margen" not in margin_df.columns:
        return

    margin_df["Fecha margen"] = pd.to_datetime(margin_df["Fecha margen"], errors="coerce")
    monthly_margin = (
        margin_df.dropna(subset=["Fecha margen"])
        .assign(periodo=lambda data: data["Fecha margen"].dt.to_period("M").astype(str))
        .groupby("periodo", as_index=False)
        .agg(margenes=(amount_column, "sum"))
    )
    if monthly_margin.empty:
        return

    monthly_margin["periodo_label"] = pd.to_datetime(monthly_margin["periodo"] + "-01").dt.strftime("%b %Y")
    monthly_margin["margenes_miles"] = monthly_margin["margenes"] / 1000
    monthly_margin["valor_label"] = monthly_margin["margenes_miles"].map(lambda value: f"${value:,.0f} mil")
    margin_chart = px.area(
        monthly_margin,
        x="periodo_label",
        y="margenes_miles",
        title="Tendencia mensual de cobro de margenes",
        markers=True,
        text="valor_label",
        color_discrete_sequence=["#2563eb"],
    )
    margin_chart.update_traces(
        line_width=4,
        marker_size=10,
        fillcolor="rgba(37, 99, 235, 0.16)",
        textposition="top center",
        textfont={"size": 13, "color": "#082f63"},
    )
    style_chart(margin_chart, x_title="Mes", y_title="Margenes cobrados (miles de $)", height=430)
    margin_chart.update_xaxes(type="category")
    margin_chart.update_yaxes(tickprefix="$", ticksuffix=" mil", separatethousands=True)
    st.plotly_chart(margin_chart, width="stretch")


def _count_units(df: pd.DataFrame, unit_column: str | None) -> int:
    if df.empty:
        return 0
    if unit_column and unit_column in df.columns:
        values = df[unit_column].dropna().astype(str).str.strip()
        values = values[values != ""]
        return values.nunique()
    return len(df)


def _not_empty(series: pd.Series) -> pd.Series:
    return series.notna() & (series.astype(str).str.strip() != "")


def _filter_plan_savings_rows(df: pd.DataFrame) -> pd.DataFrame:
    channel_columns = [column for column in ["Canal Vta.", "Canal Vta", "Canal Venta"] if column in df.columns]
    if not channel_columns:
        return df.iloc[0:0].copy()

    channel = df[channel_columns[0]].fillna("").astype(str).str.upper()
    return df[channel.str.contains("PLAN", na=False) & channel.str.contains("AHORRO", na=False)].copy()


def _deduplicate_txt_view(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Pedido ABCnet" not in df.columns:
        return df.copy()

    view = df.copy()
    view["_pedido_key"] = view["Pedido ABCnet"].map(_normalize_display_key)
    view = view[view["_pedido_key"] != ""].copy()
    if view.empty:
        return df.copy()

    view["_completeness"] = view.apply(lambda row: row.notna().sum(), axis=1)
    view["_last_sort"] = pd.to_datetime(view.get("last_imported_at"), errors="coerce")
    view = view.sort_values(["_pedido_key", "_completeness", "_last_sort"], ascending=[True, True, True])
    view = view.drop_duplicates("_pedido_key", keep="last")
    return view.drop(columns=["_pedido_key", "_completeness", "_last_sort"], errors="ignore")


def _normalize_display_key(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return "".join(re.findall(r"\d+", text))


def to_excel_bytes(df: pd.DataFrame, sheet_name: str) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


def render_data(records: pd.DataFrame) -> None:
    if records.empty:
        st.info("Sin datos para mostrar.")
        return

    df = records.copy()
    with st.sidebar:
        with st.expander("Herramientas de datos", expanded=True):
            search = st.text_input("Buscar en la base")
            st.download_button(
                "Descargar CSV",
                data=df.to_csv(index=False).encode("utf-8-sig"),
                file_name="base_consolidada.csv",
                mime="text/csv",
                width="stretch",
            )

    if search:
        mask = df.astype(str).apply(lambda column: column.str.contains(search, case=False, na=False)).any(axis=1)
        df = df[mask]

        render_dataframe(df)


def render_history(conn) -> None:
    imports = load_imports(conn)
    txt_imports = load_txt_imports(conn)
    cuenta_h_imports = load_cuenta_h_imports(conn)
    subscription_imports = load_subscription_imports(conn)

    st.subheader("Importaciones Excel")
    if imports.empty:
        st.info("Todavia no hay importaciones Excel registradas.")
    else:
        render_dataframe(imports)

    st.subheader("Importaciones TXT")
    if txt_imports.empty:
        st.info("Todavia no hay importaciones TXT registradas.")
    else:
        render_dataframe(txt_imports)

    st.subheader("Importaciones Cuenta H")
    if cuenta_h_imports.empty:
        st.info("Todavia no hay importaciones Cuenta H registradas.")
    else:
        render_dataframe(cuenta_h_imports)

    st.subheader("Importaciones Suscripciones")
    if subscription_imports.empty:
        st.info("Todavia no hay importaciones Suscripciones registradas.")
    else:
        render_dataframe(subscription_imports)


def render_kpi_grid(cards: list[tuple[str, str, str, str]]) -> None:
    html_cards = []
    for title, value, subtitle, accent in cards:
        html_cards.append(
            f"<div class='kpi-card accent-{accent}'>"
            "<div class='kpi-topline'>"
            f"<span>{title}</span>"
            "<i></i>"
            "</div>"
            f"<strong>{value}</strong>"
            f"<small>{subtitle}</small>"
            "</div>"
        )
    render_html(f"<div class='kpi-grid'>{''.join(html_cards)}</div>")


def render_dataframe(df: pd.DataFrame) -> None:
    st.dataframe(
        df,
        width="stretch",
        column_config=money_column_config(df),
    )


def money_column_config(df: pd.DataFrame) -> dict:
    config = {}
    for column in df.columns:
        if _is_money_column(column):
            config[column] = st.column_config.NumberColumn(
                str(column),
                format="$ %,.2f",
            )
    return config


def _is_money_column(column) -> bool:
    normalized = str(column).strip().lower()
    normalized = normalized.replace("_", " ")

    excluded_terms = [
        "fecha",
        "grupo",
        "orden",
        "contrato",
        "suscripcion",
        "cuota",
        "archivo",
        "concepto",
        "codigo",
        "nro",
        "numero",
        "id",
        "hash",
        "imported at",
    ]
    if any(term in normalized for term in excluded_terms):
        return False

    exact_money_columns = {
        "valor",
        "importe",
        "debito",
        "credito",
        "saldo",
        "debe",
        "haber",
        "facturacion",
        "importe margen",
        "margen total",
        "total margen",
        "total margen concepto",
        "total margenes",
        "margen venta 1ra parte",
        "margen venta 2da parte",
        "margen cambio modelo contado",
    }
    if normalized in exact_money_columns:
        return True

    return normalized.startswith("importe ") or normalized.startswith("margen ")


def render_html(html: str) -> None:
    if hasattr(st, "html"):
        st.html(html)
        return
    st.markdown(html, unsafe_allow_html=True)


def style_chart(
    fig,
    *,
    x_title: str | None = None,
    y_title: str | None = None,
    height: int = 390,
    show_legend: bool = True,
    show_coloraxis: bool = True,
):
    fig.update_layout(
        template="plotly_white",
        height=height,
        paper_bgcolor="rgba(255,255,255,0)",
        plot_bgcolor="#ffffff",
        font={"family": "Arial, sans-serif", "color": "#102033", "size": 12},
        title={"font": {"size": 18, "color": "#082f63"}, "x": 0.02, "xanchor": "left"},
        margin={"l": 52, "r": 28, "t": 72, "b": 52},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "font": {"color": "#102033"},
        },
        showlegend=show_legend,
    )
    fig.update_xaxes(
        title=x_title,
        showgrid=False,
        zeroline=False,
        linecolor="#d7e6f7",
        tickfont={"color": "#52677f"},
        title_font={"color": "#102033"},
    )
    fig.update_yaxes(
        title=y_title,
        gridcolor="#e8f1fb",
        zeroline=False,
        linecolor="#d7e6f7",
        tickfont={"color": "#52677f"},
        title_font={"color": "#102033"},
    )
    if not show_coloraxis:
        fig.update_layout(coloraxis_showscale=False)
    return fig


def _unique_count_for(df: pd.DataFrame, column: str, value: str) -> int:
    if column not in df.columns:
        return 0
    return df[df[column] == value]["matricula"].replace("", pd.NA).nunique()


def first_existing_column(df: pd.DataFrame, columns: list[str]) -> str:
    for column in columns:
        if column in df.columns:
            return column
    return columns[-1]


def month_name_es(month: int) -> str:
    names = {
        1: "Enero",
        2: "Febrero",
        3: "Marzo",
        4: "Abril",
        5: "Mayo",
        6: "Junio",
        7: "Julio",
        8: "Agosto",
        9: "Septiembre",
        10: "Octubre",
        11: "Noviembre",
        12: "Diciembre",
    }
    return names.get(int(month), str(month))


def count_brand_subscriptions(df: pd.DataFrame, brand: str) -> int:
    if "marca" not in df.columns:
        return 0
    return int(df["marca"].fillna("").astype(str).str.contains(brand, case=False, na=False).sum())


def _format_number(value) -> str:
    return f"{value:,.0f}"


def _format_currency(value) -> str:
    return f"${value:,.0f}"


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --blue-950: #082f63;
            --blue-900: #0f3f8c;
            --blue-800: #0b5cad;
            --blue-700: #1d4ed8;
            --blue-600: #2563eb;
            --blue-100: #dbeafe;
            --blue-50: #eff6ff;
            --text-main: #102033;
            --text-muted: #52677f;
            --white: #ffffff;
        }

        .stApp {
            background:
                radial-gradient(circle at top right, rgba(14, 165, 233, 0.12), transparent 28%),
                linear-gradient(180deg, #f8fbff 0%, #edf5ff 100%);
            color: var(--text-main);
        }

        .block-container {
            padding-top: 3.4rem;
            padding-bottom: 3rem;
            max-width: 1540px;
        }

        .page-hero {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 24px;
            background: linear-gradient(135deg, #082f63 0%, #0b5cad 54%, #0ea5e9 100%);
            border: 1px solid rgba(255, 255, 255, 0.62);
            border-radius: 16px;
            padding: 28px 32px;
            margin-bottom: 22px;
            box-shadow: 0 20px 48px rgba(15, 63, 140, 0.18);
        }

        .page-hero h1 {
            margin: 4px 0 6px 0;
            color: #ffffff;
            font-size: 34px;
            line-height: 1.14;
            font-weight: 800;
        }

        .page-hero .eyebrow {
            margin: 0;
            color: #bfdbfe;
            font-size: 13px;
            font-weight: 800;
            text-transform: uppercase;
        }

        .page-hero .hero-copy {
            margin: 0;
            color: #eaf6ff;
            font-size: 15px;
            font-weight: 500;
        }

        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
            margin: 8px 0 16px 0;
        }

        .kpi-card {
            position: relative;
            overflow: hidden;
            background: rgba(255, 255, 255, 0.94);
            border: 1px solid #d8e8fb;
            border-radius: 14px;
            padding: 18px 18px 16px 18px;
            min-height: 126px;
            box-shadow: 0 14px 34px rgba(15, 63, 140, 0.10);
        }

        .kpi-card::before {
            content: "";
            position: absolute;
            inset: 0 auto 0 0;
            width: 5px;
            background: #2563eb;
        }

        .kpi-card::after {
            content: "";
            position: absolute;
            right: -44px;
            top: -44px;
            width: 108px;
            height: 108px;
            border-radius: 999px;
            background: rgba(37, 99, 235, 0.10);
        }

        .kpi-card.accent-sky::before { background: #0ea5e9; }
        .kpi-card.accent-sky::after { background: rgba(14, 165, 233, 0.12); }
        .kpi-card.accent-indigo::before { background: #4f46e5; }
        .kpi-card.accent-indigo::after { background: rgba(79, 70, 229, 0.10); }
        .kpi-card.accent-cyan::before { background: #06b6d4; }
        .kpi-card.accent-cyan::after { background: rgba(6, 182, 212, 0.11); }

        .kpi-topline {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 12px;
        }

        .kpi-topline span {
            color: #52677f;
            font-size: 13px;
            font-weight: 800;
            text-transform: uppercase;
        }

        .kpi-topline i {
            display: block;
            width: 34px;
            height: 8px;
            border-radius: 999px;
            background: #dbeafe;
        }

        .kpi-card strong {
            display: block;
            color: #082f63;
            font-size: 31px;
            line-height: 1.08;
            font-weight: 800;
            letter-spacing: 0;
            margin-bottom: 8px;
        }

        .kpi-card small {
            color: #64748b;
            font-size: 13px;
            font-weight: 650;
        }

        .summary-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin: 6px 0 18px 0;
            padding: 14px;
            border-radius: 14px;
            background: rgba(219, 234, 254, 0.64);
            border: 1px solid #c8ddf6;
        }

        .summary-strip div {
            background: #ffffff;
            border-radius: 10px;
            padding: 12px 14px;
            border: 1px solid #e1edf9;
        }

        .summary-strip span {
            display: block;
            color: #64748b;
            font-size: 12px;
            font-weight: 800;
            text-transform: uppercase;
            margin-bottom: 4px;
        }

        .summary-strip strong {
            color: #082f63;
            font-size: 18px;
        }

        .stApp h1,
        .stApp h2,
        .stApp h3,
        .stApp h4,
        .stApp h5,
        .stApp h6,
        .stApp p,
        .stApp label,
        .stApp span,
        .stApp div {
            color: var(--text-main);
        }

        .stApp small,
        .stApp [data-testid="stCaptionContainer"] p {
            color: var(--text-muted);
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f3f8c 0%, #0b5cad 55%, #0ea5e9 100%);
        }

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] div {
            color: var(--white);
        }

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: var(--white);
        }

        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
            color: #cfe8ff;
            font-weight: 500;
        }

        [data-testid="stSidebar"] hr {
            border-color: rgba(255, 255, 255, 0.35);
        }

        .sidebar-nav {
            margin-top: 14px;
            margin-bottom: 12px;
        }

        [data-testid="stSidebar"] [role="radiogroup"] {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label,
        [data-testid="stSidebar"] [role="radiogroup"] label p,
        [data-testid="stSidebar"] [role="radiogroup"] label span {
            color: var(--white);
            font-weight: 700;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label {
            width: 100%;
            min-height: 48px;
            padding: 10px 12px;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.10);
            border: 1px solid rgba(255, 255, 255, 0.18);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
            transition: background 0.18s ease, transform 0.18s ease, border-color 0.18s ease;
            display: flex;
            align-items: center;
            justify-content: flex-start;
            box-sizing: border-box;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label:hover {
            background: rgba(255, 255, 255, 0.18);
            border-color: rgba(255, 255, 255, 0.36);
            transform: translateY(-1px);
        }

        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
            background: #ffffff;
            border-color: #ffffff;
            box-shadow: 0 10px 24px rgba(6, 31, 75, 0.22);
        }

        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p,
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) span {
            color: #0f3f8c;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {
            display: none;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label p {
            margin: 0;
            line-height: 1.2;
            font-size: 13px;
            white-space: normal;
        }

        [data-testid="stSidebar"] [data-testid="stExpander"] {
            background: rgba(255, 255, 255, 0.10);
            border: 1px solid rgba(255, 255, 255, 0.20);
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 10px;
        }

        [data-testid="stSidebar"] [data-testid="stExpander"] details {
            border: 0;
        }

        [data-testid="stSidebar"] [data-testid="stExpander"] summary {
            min-height: 42px;
            padding: 8px 10px;
        }

        [data-testid="stSidebar"] [data-testid="stExpander"] summary p {
            color: #ffffff;
            font-weight: 800;
        }

        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] textarea,
        [data-testid="stSidebar"] [data-baseweb="select"] *,
        [data-testid="stSidebar"] [data-baseweb="input"] *,
        [data-testid="stSidebar"] [data-baseweb="textarea"] * {
            color: var(--text-main);
        }

        [data-testid="stSidebar"] input::placeholder,
        [data-testid="stSidebar"] textarea::placeholder {
            color: #6b7f96;
        }

        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid rgba(255, 255, 255, 0.9);
        }

        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] *,
        [data-testid="stSidebar"] [data-testid="stFileUploaderFile"] * {
            color: var(--text-main);
        }

        [data-testid="stSidebar"] [data-testid="stMetric"] {
            background: var(--white);
            border: 1px solid rgba(255, 255, 255, 0.7);
            border-radius: 12px;
            box-shadow: 0 10px 24px rgba(6, 31, 75, 0.24);
        }

        [data-testid="stSidebar"] [data-testid="stMetric"] label,
        [data-testid="stSidebar"] [data-testid="stMetric"] div,
        [data-testid="stSidebar"] [data-testid="stMetric"] p,
        [data-testid="stSidebar"] [data-testid="stMetric"] span {
            color: var(--text-main);
        }

        [data-testid="stSidebar"] .stButton > button,
        [data-testid="stSidebar"] .stDownloadButton > button {
            background: var(--white);
            border: 0;
            color: var(--blue-900);
            font-weight: 700;
            border-radius: 8px;
        }

        [data-testid="stSidebar"] .stButton > button *,
        [data-testid="stSidebar"] .stDownloadButton > button * {
            color: var(--blue-900);
        }

        [data-testid="stSidebar"] .stButton > button:hover,
        [data-testid="stSidebar"] .stDownloadButton > button:hover {
            background: var(--blue-100);
            color: var(--blue-800);
        }

        [data-testid="stMetric"] {
            background: var(--white);
            border: 1px solid var(--blue-100);
            border-radius: 12px;
            padding: 14px 16px;
            box-shadow: 0 8px 20px rgba(15, 63, 140, 0.08);
        }

        [data-testid="stMetric"] label,
        [data-testid="stMetric"] div,
        [data-testid="stMetric"] p,
        [data-testid="stMetric"] span {
            color: var(--text-main);
        }

        .stAlert {
            background: #d9ecff;
            border: 1px solid #b8dcff;
            color: var(--blue-950);
        }

        .stAlert *,
        .stAlert p,
        .stAlert div,
        .stAlert span {
            color: var(--blue-950);
        }

        .stButton > button,
        .stDownloadButton > button {
            color: var(--white);
            background: var(--blue-600);
            border: 1px solid var(--blue-600);
            font-weight: 700;
            border-radius: 8px;
        }

        .stButton > button *,
        .stDownloadButton > button * {
            color: inherit;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover {
            background: var(--blue-700);
            border-color: var(--blue-700);
            color: var(--white);
        }

        input,
        textarea,
        [data-baseweb="select"] *,
        [data-baseweb="input"] *,
        [data-baseweb="textarea"] * {
            color: var(--text-main);
        }

        div[data-testid="stDataFrame"] *,
        [data-testid="stTable"] * {
            color: var(--text-main);
        }

        div[data-testid="stDataFrame"] {
            border: 1px solid var(--blue-100);
            border-radius: 12px;
            overflow: hidden;
        }

        [data-testid="stPlotlyChart"] {
            background: #ffffff;
            border: 1px solid #d8e8fb;
            border-radius: 16px;
            padding: 12px 12px 4px 12px;
            box-shadow: 0 16px 38px rgba(15, 63, 140, 0.10);
            margin-bottom: 16px;
        }

        .js-plotly-plot text {
            fill: var(--text-main);
        }

        @media (max-width: 1100px) {
            .kpi-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .summary-strip {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }

        @media (max-width: 680px) {
            .page-hero {
                padding: 22px;
            }

            .page-hero h1 {
                font-size: 25px;
            }

            .kpi-grid,
            .summary-strip {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _normalize_for_select(column: str) -> str:
    from transform import _normalize_column_name

    return _normalize_column_name(column)


if __name__ == "__main__":
    main()
