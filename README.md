# Subnet Cleanse Dashboard

Dashboard local para dar seguimiento a la limpieza de subredes marcadas
"FREE" en 1DDI que en realidad tienen conflictos, detectados por el
reporte de reconciliación de SSOT (`ddi_reconciliation`).

Es una herramienta **independiente de SSOT** — solo lee el CSV que ese
reporte ya genera; no se conecta ni escribe nada en SSOT, 1DDI o FMC.

## Casos que muestra

- **Caso 1 — FREE but IN USE**: la subred está en uso real, pero 1DDI no
  se actualizó. Acción: corregir el Site ID en 1DDI.
- **Caso 2 — FREE but REFERENCED**: la subred no está en uso, pero quedan
  objetos/reglas de firewall (FMC) referenciándola. Acción: pedir borrado
  al equipo de firewall.

Cada subred tiene una columna **Estado** (Pendiente / Solicitado /
Resuelto) que se guarda localmente en `estado_subnets.db` y no se pierde
al cargar un CSV nuevo el mes siguiente.

## Requisitos

```bash
pip install -r requirements.txt
```

## Cómo obtener el CSV cada mes (en ssot-dev, por SSH)

```bash
cd /opt/dn/ssot
source venv/bin/activate
python -m reports.ddi_reconciliation --conflicts-only --csv
```

Esto escribe `reports/ddi_reconciliation/ddi_reconciliation_<fecha>.csv`.
Bájalo a tu laptop, por ejemplo:

```bash
scp usuario@ssot-dev:/dn/ssot/reports/ddi_reconciliation/ddi_reconciliation_<fecha>.csv .
```

## Cómo correr el dashboard

```bash
streamlit run subnet_cleanse_dashboard.py
```

Se abre en `http://localhost:8501`. Sube ahí el CSV descargado.
