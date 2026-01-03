import os
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from telegram import Update, InputFile
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("TOKEN")  # Railway lee el token desde Variables
HEADERS = {"User-Agent": "Mozilla/5.0"}
MIN_PARTIDOS_ALERTA = 7

# =========================
# FETCH STATMUSE
# =========================
def fetch_statmuse(player, mode="full", last_n=10, vs_team=None):
    name = player.lower().replace(" ", "-")

    if mode == "1q":
        url = f"https://www.statmuse.com/nba/ask/{name}-stats-1q-gamelog"
    else:
        url = f"https://www.statmuse.com/nba/ask/{name}-gamelog"

    if vs_team:
        vs = vs_team.lower().replace(" ", "-")
        url += f"-vs-{vs}"

    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        return None, "Error cargando StatMuse"

    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table")
    if table is None:
        return None, "No se encontraron datos"

    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    rows = []

    for tr in table.find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if cells:
            rows.append(cells)

    df = pd.DataFrame(rows, columns=headers)

    if "DATE" in df.columns:
        df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
        df = df[df["DATE"] <= datetime.now() - timedelta(days=1)]
        df = df.sort_values("DATE", ascending=False).head(last_n)

    return df, None

# =========================
# IMAGE GENERATOR
# =========================
def generate_image(df, title, mode="full"):
    width = 820
    row_h = 40
    header_h = 90
    footer_h = 40
    height = header_h + len(df) * row_h + footer_h

    img = Image.new("RGB", (width, height), "#111827")
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("arialbd.ttf", 26)
        font = ImageFont.truetype("arial.ttf", 18)
        font_bold = ImageFont.truetype("arialbd.ttf", 18)
        font_footer = ImageFont.truetype("arial.ttf", 14)
    except:
        font_title = font = font_bold = font_footer = ImageFont.load_default()

    # Fondo degradado solo 1Q
    if mode == "1q":
        for y in range(header_h, height - footer_h):
            r = int(17 + (y-header_h)/(height-header_h-footer_h)*(45-17))
            g = int(24 + (y-header_h)/(height-header_h-footer_h)*(59-24))
            b = int(39 + (y-header_h)/(height-header_h-footer_h)*(92-39))
            draw.line([(0, y), (width, y)], fill=(r, g, b))

    draw.text((width//2, 20), title, fill="white", font=font_title, anchor="mm")

    cols = ["DATE","TM","OPP","MIN","PTS","REB","AST","FG","3PT","PF"]
    x = [20, 90, 140, 200, 260, 320, 380, 440, 520, 600]

    for i, c in enumerate(cols):
        draw.text((x[i], 60), c, fill="#facc15", font=font)

    for i, row in df.iterrows():
        y = header_h + df.index.get_loc(i) * row_h

        fg = f"{row.get('FGM','0')}/{row.get('FGA','0')}"
        t3 = f"{row.get('3PM','0')}/{row.get('3PA','0')}"
        date_str = row["DATE"].strftime("%d/%m/%Y") if "DATE" in row and pd.notnull(row["DATE"]) else "-"

        values = [
            date_str,
            row.get("TM","-"),
            row.get("OPP","-"),
            row.get("MIN","-"),
            row.get("PTS","0"),
            row.get("REB","0"),
            row.get("AST","0"),
            fg,
            t3,
            row.get("PF","0")
        ]

        for j, val in enumerate(values):
            draw_font = font
            try:
                v = float(val.split("/")[0]) if "/" in str(val) else float(val)
            except:
                v = 0

            if mode == "1q":
                if (j==4 and v>=6) or (j==5 and v>=2) or (j==6 and v>=2) or (j==8 and v>=3):
                    draw_font = font_bold
            else:
                if (j==4 and v>=25) or (j==5 and v>=7) or (j==6 and v>=7) or (j==8 and v>=3):
                    draw_font = font_bold

            draw.text((x[j], y), str(val), fill="white", font=draw_font)

    draw.text((width//2, height-20), "CREADO POR 24", fill="#9ca3af", font=font_footer, anchor="mm")

    bio = BytesIO()
    bio.name = "stats.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

# =========================
# TELEGRAM HANDLER
# =========================
def handle_message(update: Update, context: CallbackContext):
    txt = update.message.text.lower().strip()
    update.message.reply_text("BUSCANDO STATS...")

    mode = "full"
    last_n = 10
    vs_team = None

    if "1q" in txt:
        mode = "1q"
        txt = txt.replace("1q","").strip()

    vs = re.search(r"vs\s+(.+)", txt)
    if vs:
        vs_team = vs.group(1).strip()
        player = txt.split("vs")[0].strip()
        last_n = 5
    else:
        player = txt.strip()

    df, error = fetch_statmuse(player, mode, last_n, vs_team)
    if error or df is None or df.empty:
        update.message.reply_text("NO SE ENCONTRARON DATOS")
        return

    thresholds = {"PTS":6,"REB":2,"AST":2,"3PM":3} if mode=="1q" else {"PTS":25,"REB":7,"AST":7,"3PM":3}
    alertas = []

    for stat, val in thresholds.items():
        count = sum(float(row.get(stat,0)) >= val for _, row in df.iterrows())
        if count >= MIN_PARTIDOS_ALERTA:
            alertas.append(f"{val} {stat}: {count}/{len(df)}")

    if alertas:
        modo_txt = "EN EL 1Q" if mode=="1q" else "EN EL PARTIDO COMPLETO"
        msg = f"🔥 **{player.upper()} HA SUPERADO {modo_txt}:**\n" + "\n".join([f"**{a}**" for a in alertas])
        update.message.reply_text(msg, parse_mode="Markdown")

    title = f"{player.title()} - {'1Q' if mode=='1q' else 'FULL GAME'}"
    if vs_team:
        title += f" vs {vs_team.title()}"

    img = generate_image(df, title, mode)
    update.message.reply_photo(photo=InputFile(img))

# =========================
# BOT START
# =========================
updater = Updater(TOKEN, use_context=True)
dp = updater.dispatcher
dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

print("Bot iniciado")
updater.start_polling()
updater.idle()
