"""
mapa_onde_estamos.py
Gera a página final "Onde Estamos" do Diário Gov.BR.
Mapa vetorial gerado em código — sem dependência de arquivo externo.
Suporta qualquer estado brasileiro e qualquer país do mundo.
"""
import os, re, io, math, json, tempfile, urllib.request
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from PIL import Image as PILImage, ImageDraw

PW, PH = A4
MARGIN = 15 * mm

VERDE_ESCURO = colors.HexColor("#2D6A1F")
VERDE_MEDIO  = colors.HexColor("#4FAE32")
AMARELO      = colors.HexColor("#FFD008")
PRETO        = colors.HexColor("#1A1A1A")
BRANCO       = colors.white
CINZA_PAIS   = colors.HexColor("#CCCCCC")
CINZA_ESTADO = colors.HexColor("#BBBBBB")
CINZA_BORDA  = colors.white

# ── Cache de GeoJSON (carregado uma vez) ─────────────────────────────────────
_cache = {}

def _baixar_geojson(url):
    """Baixa e cacheia GeoJSON."""
    if url in _cache:
        return _cache[url]
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode('utf-8'))
        _cache[url] = data
        return data
    except Exception as e:
        print(f"  ⚠ Não foi possível baixar GeoJSON: {e}")
        return None

GEOJSON_BRASIL = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
GEOJSON_MUNDO  = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"

# ── Projeção ─────────────────────────────────────────────────────────────────
def _mercator_xy(lon, lat, bbox, w, h):
    """Projeta lon/lat → (x, y) em pixels dentro da bbox."""
    x0, y0_lat, x1, y1_lat = bbox
    x = (lon - x0) / (x1 - x0) * w

    def merc(la):
        r = math.radians(la)
        return math.log(math.tan(math.pi/4 + r/2))

    m  = merc(lat)
    m0 = merc(y0_lat)
    m1 = merc(y1_lat)
    y  = (1 - (m - m0) / (m1 - m0)) * h
    return x, y

def _polygon_to_pts(coords, bbox, w, h):
    """Converte lista de [lon, lat] para lista de (x, y)."""
    pts = []
    for lon, lat in coords:
        x, y = _mercator_xy(lon, lat, bbox, w, h)
        pts.append((x, y))
    return pts

# ── Desenho de polígono no canvas ─────────────────────────────────────────────
def _draw_polygon(c, pts, fill_color, stroke_color=CINZA_BORDA, lw=0.5):
    if len(pts) < 3:
        return
    c.setFillColor(fill_color)
    c.setStrokeColor(stroke_color)
    c.setLineWidth(lw)
    p = c.beginPath()
    p.moveTo(pts[0][0], pts[0][1])
    for x, y in pts[1:]:
        p.lineTo(x, y)
    p.close()
    c.drawPath(p, fill=1, stroke=1)

def _draw_feature(c, feature, bbox, ox, oy, w, h, fill_color):
    """Desenha um feature GeoJSON (Polygon ou MultiPolygon)."""
    geom = feature.get('geometry', {})
    gtype = geom.get('type', '')

    def transform(ring):
        pts = _polygon_to_pts(ring, bbox, w, h)
        # Transladar para origem (ox, oy) e inverter y
        return [(ox + x, oy + h - y) for x, y in pts]

    if gtype == 'Polygon':
        rings = geom.get('coordinates', [])
        if rings:
            _draw_polygon(c, transform(rings[0]), fill_color)

    elif gtype == 'MultiPolygon':
        for polygon in geom.get('coordinates', []):
            if polygon:
                _draw_polygon(c, transform(polygon[0]), fill_color)

# ── Centralizar Brasil + países visitados ─────────────────────────────────────
def _calcular_bbox(locais_internacionais):
    """
    Calcula o bounding box do mapa baseado nos destinos.
    Se só Brasil: bbox padrão do Brasil.
    Se tem países: expandir para incluir todos.
    """
    # Bbox padrão do Brasil
    brasil_bbox = (-74, -34, -28, 6)

    if not locais_internacionais:
        return brasil_bbox, False

    lon_min, lat_min, lon_max, lat_max = brasil_bbox
    tem_internacional = False

    for pais, (lon_c, lat_c) in locais_internacionais.items():
        if lon_c is None:
            continue
        tem_internacional = True
        margem = 8
        lon_min = min(lon_min, lon_c - margem)
        lat_min = min(lat_min, lat_c - margem)
        lon_max = max(lon_max, lon_c + margem)
        lat_max = max(lat_max, lat_c + margem)

    return (lon_min, lat_min, lon_max, lat_max), tem_internacional

# ── Centróides dos países (para posicionamento do pin) ───────────────────────
# Principais destinos de ministros brasileiros
CENTROIDES_PAISES = {
    # América do Sul
    'Argentina':  (-63.6, -38.4),
    'Bolívia':    (-64.9, -16.3),
    'Brasil':     (-51.9, -14.2),
    'Chile':      (-71.5, -35.7),
    'Colômbia':   (-74.3,   4.6),
    'Equador':    (-78.1,  -1.8),
    'Paraguai':   (-58.4, -23.4),
    'Peru':       (-75.0,  -9.2),
    'Uruguai':    (-55.8, -32.5),
    'Venezuela':  (-66.6,   6.4),
    # América Central e Caribe
    'México':     (-102.6, 23.6),
    'Cuba':       (-79.5,  21.5),
    'Haiti':      (-72.3,  18.9),
    # América do Norte
    'EUA':        (-100.4, 37.1),
    'Canadá':     (-96.8,  56.1),
    # Europa
    'Portugal':   (-8.2,   39.4),
    'Espanha':    (-3.7,   40.4),
    'França':     (2.3,    46.2),
    'Itália':     (12.6,   41.9),
    'Alemanha':   (10.5,   51.2),
    'Reino Unido':(  -3.4,  55.4),
    'Bélgica':    (4.5,    50.5),
    'Holanda':    (5.3,    52.1),
    'Suíça':      (8.2,    46.8),
    'Áustria':    (14.6,   47.7),
    'Suécia':     (18.6,   60.1),
    'Noruega':    (8.5,    60.5),
    'Finlândia':  (25.7,   61.9),
    'Dinamarca':  (10.0,   56.3),
    'Grécia':     (21.8,   39.1),
    'Polônia':    (19.1,   52.1),
    'República Tcheca': (15.5, 49.8),
    'Hungria':    (19.5,   47.2),
    'Rússia':     (37.6,   55.8),
    'Ucrânia':    (32.0,   49.0),
    # África
    'África do Sul':  (25.1, -29.0),
    'Angola':     (17.9, -11.2),
    'Moçambique': (35.0, -18.7),
    'Cabo Verde': (-23.6, 15.1),
    'Senegal':    (-14.5, 14.5),
    'Nigéria':    (8.7,    9.1),
    'Etiópia':    (40.5,   9.1),
    'Quênia':     (37.9,   0.0),
    'Egito':      (30.8,   26.8),
    'Marrocos':   (-7.1,   31.8),
    # Oriente Médio
    'Emirados Árabes': (53.8, 23.4),
    'Arábia Saudita':  (45.1, 23.9),
    'Turquia':    (35.2,   39.0),
    'Israel':     (34.9,   31.5),
    'Jordânia':   (36.2,   31.2),
    'Irã':        (53.7,   32.4),
    'Catar':      (51.2,   25.4),
    # Ásia
    'China':      (104.2,  35.9),
    'Japão':      (138.3,  36.2),
    'Coreia do Sul': (127.8, 35.9),
    'Índia':      (78.9,   20.6),
    'Paquistão':  (69.3,   30.4),
    'Indonésia':  (113.9,  -0.8),
    'Tailândia':  (101.0,  15.9),
    'Vietnã':     (108.3,  14.1),
    'Singapura':  (103.8,   1.4),
    'Malásia':    (109.7,   1.5),
    'Filipinas':  (122.9,  12.9),
    'Bangladesh': (90.4,   23.7),
    # Oceania
    'Austrália':  (133.8, -25.7),
    'Nova Zelândia': (172.0, -41.3),
}

# ── Nomes alternativos → nome padrão ─────────────────────────────────────────
ALIAS_PAISES = {
    'eua': 'EUA', 'estados unidos': 'EUA', 'usa': 'EUA',
    'estados unidos da america': 'EUA', 'estados unidos da améric': 'EUA',
    'china': 'China', 'pequim': 'China', 'beijing': 'China',
    'xangai': 'China', 'shanghai': 'China', 'chengdu': 'China',
    'argentina': 'Argentina', 'buenos aires': 'Argentina',
    'alemanha': 'Alemanha', 'berlim': 'Alemanha',
    'franca': 'França', 'frança': 'França', 'paris': 'França',
    'italia': 'Itália', 'itália': 'Itália', 'roma': 'Itália',
    'portugal': 'Portugal', 'lisboa': 'Portugal',
    'espanha': 'Espanha', 'madri': 'Espanha', 'madrid': 'Espanha',
    'mexico': 'México', 'méxico': 'México', 'cidade do mexico': 'México',
    'colombia': 'Colômbia', 'colômbia': 'Colômbia', 'bogota': 'Colômbia',
    'peru': 'Peru', 'lima': 'Peru',
    'uruguai': 'Uruguai', 'montevideu': 'Uruguai',
    'paraguai': 'Paraguai', 'assuncao': 'Paraguai',
    'bolivia': 'Bolívia', 'bolívia': 'Bolívia',
    'chile': 'Chile', 'santiago': 'Chile',
    'venezuela': 'Venezuela', 'caracas': 'Venezuela',
    'japao': 'Japão', 'japão': 'Japão', 'toquio': 'Japão', 'tóquio': 'Japão',
    'india': 'Índia', 'índia': 'Índia', 'nova delhi': 'Índia',
    'russia': 'Rússia', 'rússia': 'Rússia', 'moscou': 'Rússia',
    'africa do sul': 'África do Sul', 'joanesburgo': 'África do Sul',
    'angola': 'Angola', 'luanda': 'Angola',
    'mozambique': 'Moçambique', 'moçambique': 'Moçambique',
    'canada': 'Canadá', 'canadá': 'Canadá',
    'reino unido': 'Reino Unido', 'inglaterra': 'Reino Unido', 'londres': 'Reino Unido',
    'australia': 'Austrália', 'austrália': 'Austrália',
    'turquia': 'Turquia', 'istambul': 'Turquia', 'ancara': 'Turquia',
    'emirados arabes': 'Emirados Árabes', 'dubai': 'Emirados Árabes',
    'arabia saudita': 'Arábia Saudita', 'riad': 'Arábia Saudita',
    'catar': 'Catar', 'qatar': 'Catar', 'doha': 'Catar',
    'israel': 'Israel', 'tel aviv': 'Israel',
    'coreia do sul': 'Coreia do Sul', 'seoul': 'Coreia do Sul', 'seul': 'Coreia do Sul',
    'singapura': 'Singapura', 'singapore': 'Singapura',
    'tailandia': 'Tailândia', 'tailândia': 'Tailândia', 'bangkok': 'Tailândia',
    'indonesia': 'Indonésia', 'indonésia': 'Indonésia', 'jacarta': 'Indonésia',
    'egito': 'Egito', 'cairo': 'Egito',
    'marrocos': 'Marrocos', 'rabat': 'Marrocos',
    'nigeria': 'Nigéria', 'nigéria': 'Nigéria',
    'etiopia': 'Etiópia', 'etiópia': 'Etiópia', 'adis abeba': 'Etiópia',
    'kenya': 'Quênia', 'quenia': 'Quênia', 'quênia': 'Quênia', 'nairobi': 'Quênia',
    'senegal': 'Senegal', 'dakar': 'Senegal',
    'cabo verde': 'Cabo Verde', 'praia': 'Cabo Verde',
    'belgica': 'Bélgica', 'bélgica': 'Bélgica', 'bruxelas': 'Bélgica',
    'holanda': 'Holanda', 'amsterdam': 'Holanda',
    'suecia': 'Suécia', 'suécia': 'Suécia', 'estocolmo': 'Suécia',
    'noruega': 'Noruega', 'oslo': 'Noruega',
    'suica': 'Suíça', 'suíça': 'Suíça', 'genebra': 'Suíça', 'zurique': 'Suíça',
    'austria': 'Áustria', 'áustria': 'Áustria', 'viena': 'Áustria',
    'grecia': 'Grécia', 'grécia': 'Grécia', 'atenas': 'Grécia',
    'polonia': 'Polônia', 'polônia': 'Polônia', 'varsovia': 'Polônia',
    'cuba': 'Cuba', 'havana': 'Cuba',
    'haiti': 'Haiti', 'porto principe': 'Haiti',
    'vietna': 'Vietnã', 'vietnã': 'Vietnã', 'hanói': 'Vietnã',
    'malasia': 'Malásia', 'malásia': 'Malásia', 'kuala lumpur': 'Malásia',
    'filipinas': 'Filipinas', 'manila': 'Filipinas',
    'bangladesh': 'Bangladesh', 'dhaka': 'Bangladesh',
    'paquistao': 'Paquistão', 'paquistão': 'Paquistão', 'islamabad': 'Paquistão',
    'nova zelandia': 'Nova Zelândia', 'nova zelândia': 'Nova Zelândia',
    'ira': 'Irã', 'irã': 'Irã', 'teerã': 'Irã',
    'jordania': 'Jordânia', 'jordânia': 'Jordânia', 'amã': 'Jordânia',
}

UFS = {'AC','AL','AM','AP','BA','CE','DF','ES','GO','MA','MG','MS','MT',
       'PA','PB','PE','PI','PR','RJ','RN','RO','RR','RS','SC','SE','SP','TO'}

CIDADES_UF = {
    'rio de janeiro': 'RJ', 'niterói': 'RJ', 'niteri': 'RJ',
    'são paulo': 'SP', 'campinas': 'SP', 'santos': 'SP',
    'minas gerais': 'MG', 'belo horizonte': 'MG', 'uberlândia': 'MG',
    'bahia': 'BA', 'salvador': 'BA', 'feira de santana': 'BA',
    'rio grande do sul': 'RS', 'porto alegre': 'RS', 'pântano grande': 'RS', 'caxias': 'RS',
    'paraná': 'PR', 'curitiba': 'PR', 'londrina': 'PR',
    'santa catarina': 'SC', 'florianópolis': 'SC', 'joinville': 'SC',
    'pernambuco': 'PE', 'recife': 'PE', 'caruaru': 'PE',
    'ceará': 'CE', 'fortaleza': 'CE', 'juazeiro': 'CE',
    'goiás': 'GO', 'goiânia': 'GO', 'anápolis': 'GO',
    'mato grosso': 'MT', 'cuiabá': 'MT',
    'mato grosso do sul': 'MS', 'campo grande': 'MS',
    'pará': 'PA', 'belém': 'PA', 'santarém': 'PA',
    'amazonas': 'AM', 'manaus': 'AM',
    'maranhão': 'MA', 'são luís': 'MA',
    'espírito santo': 'ES', 'vitória': 'ES',
    'rio branco': 'AC', 'acre': 'AC',
    'brasília': 'DF', 'distrito federal': 'DF',
    'roraima': 'RR', 'boa vista': 'RR',
    'rondônia': 'RO', 'porto velho': 'RO',
    'amapá': 'AP', 'macapá': 'AP',
    'tocantins': 'TO', 'palmas': 'TO',
    'piauí': 'PI', 'teresina': 'PI',
    'rio grande do norte': 'RN', 'natal': 'RN',
    'paraíba': 'PB', 'joão pessoa': 'PB',
    'alagoas': 'AL', 'maceió': 'AL',
    'sergipe': 'SE', 'aracaju': 'SE',
}

# Centroides dos estados brasileiros (lon, lat)
CENTROIDES_UF = {
    'AC': (-70.5, -9.0),  'AL': (-36.6, -9.5),   'AM': (-64.7, -3.4),
    'AP': (-51.1,  1.4),  'BA': (-41.7,-12.5),   'CE': (-39.5, -5.1),
    'DF': (-47.9,-15.8),  'ES': (-40.7,-19.6),   'GO': (-49.6,-15.8),
    'MA': (-45.3, -5.4),  'MG': (-44.7,-18.5),   'MS': (-54.8,-20.5),
    'MT': (-56.1,-12.7),  'PA': (-53.1, -3.5),   'PB': (-36.8, -7.2),
    'PE': (-37.9, -8.8),  'PI': (-43.1, -7.4),   'PR': (-51.6,-24.9),
    'RJ': (-43.2,-22.9),  'RN': (-36.5, -5.8),   'RO': (-63.3,-10.8),
    'RR': (-61.4,  2.0),  'RS': (-53.2,-30.0),   'SC': (-50.0,-27.3),
    'SE': (-37.4,-10.6),  'SP': (-48.5,-22.3),   'TO': (-48.3,-10.2),
}

def extrair_local(titulo, bullets):
    """Extrai UF ou país normalizado."""
    texto = titulo + " " + " ".join(bullets)
    texto_lower = texto.lower()

    # 1. Sigla "(XX)" para estado
    for uf in re.findall(r'\(([A-Z]{2})\)', texto):
        if uf in UFS:
            return ('estado', uf)

    # 2. País por alias (mais específico primeiro — cidades antes de países)
    for alias, pais in sorted(ALIAS_PAISES.items(), key=lambda x: -len(x[0])):
        if alias in texto_lower:
            return ('pais', pais)

    # 3. Cidade/estado por extenso
    for cidade, uf in sorted(CIDADES_UF.items(), key=lambda x: -len(x[0])):
        if cidade in texto_lower:
            return ('estado', uf)

    return None


def fazer_foto_circular(img_bytes, tamanho=160):
    pil = PILImage.open(io.BytesIO(img_bytes)).convert("RGBA")
    w, h = pil.size
    lado = min(w, h)
    pil = pil.crop(((w-lado)//2, (h-lado)//2, (w+lado)//2, (h+lado)//2))
    pil = pil.resize((tamanho, tamanho), PILImage.LANCZOS)
    mask = PILImage.new("L", (tamanho, tamanho), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, tamanho, tamanho), fill=255)
    result = PILImage.new("RGBA", (tamanho, tamanho), (0,0,0,0))
    result.paste(pil, mask=mask)
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()


def desenhar_pin(c, cx, cy, foto_bytes, raio_mm=6.5):
    r = raio_mm * mm
    pin_h = r * 2.4
    # Sombra
    c.setFillColor(colors.HexColor("#00000022"))
    _pin_path(c, cx+0.8, cy-0.8, r*1.02, pin_h*1.02)
    c.drawPath(_pin_path(c, cx+0.8, cy-0.8, r*1.02, pin_h*1.02, ret=True), fill=1, stroke=0)
    # Corpo
    c.setFillColor(VERDE_ESCURO)
    c.drawPath(_pin_path(c, cx, cy, r, pin_h, ret=True), fill=1, stroke=0)
    # Borda
    c.setStrokeColor(VERDE_MEDIO); c.setLineWidth(1.5)
    c.drawPath(_pin_path(c, cx, cy, r, pin_h, ret=True), fill=0, stroke=1)
    # Foto
    if foto_bytes:
        try:
            fc = fazer_foto_circular(foto_bytes)
            tf = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tf.write(fc); tf.close()
            fr = r * 0.78
            c.drawImage(tf.name, cx-fr, cy-r*2+(r-fr)*0.5,
                        width=fr*2, height=fr*2, mask='auto')
            os.unlink(tf.name)
        except:
            c.setFillColor(AMARELO); c.circle(cx, cy-r, r*0.7, fill=1, stroke=0)
    else:
        c.setFillColor(colors.HexColor("#EEEEEE")); c.circle(cx, cy-r, r*0.72, fill=1, stroke=0)

def _pin_path(c, cx, cy, r, pin_h, ret=False):
    p = c.beginPath()
    p.arc(cx-r, cy-r*2, cx+r, cy, startAng=0, extent=180)
    p.lineTo(cx-r, cy-r)
    p.lineTo(cx, cy-pin_h)
    p.lineTo(cx+r, cy-r)
    p.arc(cx-r, cy-r*2, cx+r, cy, startAng=180, extent=180)
    p.close()
    if ret: return p


def _lon_lat_para_canvas(lon, lat, bbox, ox, oy, mw, mh):
    """Converte lon/lat para coordenadas do canvas."""
    x, y = _mercator_xy(lon, lat, bbox, mw, mh)
    return ox + x, oy + mh - y


def adicionar_pagina_mapa(canvas_obj, noticias, pasta_fotos, data_doc, pnum,
                          caminho_mapa_bg=None):
    """
    Adiciona página do mapa. Gera mapa vetorial automaticamente.
    Suporta qualquer estado brasileiro e qualquer país do mundo.
    """
    c = canvas_obj
    c.showPage()

    # ── Cabeçalho ────────────────────────────────────────────────────────
    c.setFillColor(BRANCO)
    c.rect(0, PH-9*mm, PW, 9*mm, fill=1, stroke=0)
    c.setFont("Helvetica", 7.5); c.setFillColor(colors.HexColor("#888888"))
    c.drawString(MARGIN, PH-6*mm,
        f"Diário Gov.BR  |  Brasília/DF  |  {data_doc}  |  Pág. {pnum}")
    c.setStrokeColor(colors.HexColor("#DDDDDD")); c.setLineWidth(0.4)
    c.line(MARGIN, PH-9*mm, PW-MARGIN, PH-9*mm)

    # ── Extrair destinos das viagens ─────────────────────────────────────
    destinos = []
    for n in noticias:
        resultado = extrair_local(n['titulo'], n['bullets'])
        if resultado:
            tipo, local = resultado
            destinos.append({
                'tipo': tipo, 'local': local,
                'ministerio': n['ministerio'], 'titulo': n['titulo']
            })

    paises_visitados = set(d['local'] for d in destinos if d['tipo'] == 'pais')
    estados_visitados = set(d['local'] for d in destinos if d['tipo'] == 'estado')

    # ── Bbox do mapa: sempre centrado no Brasil ──────────────────────────
    # Países internacionais são plotados fora da área do Brasil
    # usando coordenadas fixas nos cantos da página
    bbox = (-74, -34, -28, 6)  # Brasil fixo

    # ── Área do mapa na página ────────────────────────────────────────────
    map_x = MARGIN
    map_y = 72*mm
    map_w = PW - 2*MARGIN
    map_h = PH - 9*mm - map_y - 5*mm

    # Fundo cinza claro
    c.setFillColor(colors.HexColor("#F0F0F0"))
    c.rect(map_x-2, map_y-2, map_w+4, map_h+4, fill=1, stroke=0)

    # ── Baixar e desenhar GeoJSON dos países ─────────────────────────────
    geojson_mundo = _baixar_geojson(GEOJSON_MUNDO)
    geojson_brasil = _baixar_geojson(GEOJSON_BRASIL)

    if geojson_mundo:
        for feat in geojson_mundo.get('features', []):
            props = feat.get('properties', {})
            nome_pais = props.get('ADMIN', props.get('name', ''))
            if nome_pais in paises_visitados:
                cor = colors.HexColor("#AAAACC")  # azul claro para países visitados
            else:
                cor = CINZA_PAIS
            _draw_feature(c, feat, bbox, map_x, map_y, map_w, map_h, cor)

    # ── Desenhar estados do Brasil ────────────────────────────────────────
    if geojson_brasil:
        for feat in geojson_brasil.get('features', []):
            props = feat.get('properties', {})
            sigla = props.get('sigla', props.get('UF', props.get('abbrev', '')))
            if sigla in estados_visitados:
                cor = colors.HexColor("#AAAACC")
            else:
                cor = CINZA_ESTADO
            _draw_feature(c, feat, bbox, map_x, map_y, map_w, map_h, cor)
    else:
        # Fallback: retângulos aproximados por estado
        _desenhar_brasil_fallback(c, bbox, map_x, map_y, map_w, map_h, estados_visitados)

    # ── Bloco "ONDE estamos" ─────────────────────────────────────────────
    bx = map_x; by = map_y + map_h*0.38; bw = 42*mm; bh = 28*mm
    c.setFillColor(VERDE_MEDIO)
    c.rect(bx, by, bw, bh, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 22); c.setFillColor(AMARELO)
    c.drawString(bx+4*mm, by+17*mm, "ONDE")
    c.setFont("Helvetica-BoldOblique", 14); c.setFillColor(BRANCO)
    c.drawString(bx+4*mm, by+6*mm, "estamos")
    # Barra lateral direita decorativa
    c.setFillColor(VERDE_MEDIO)
    c.rect(PW-MARGIN-8*mm, by, 8*mm, bh, fill=1, stroke=0)

    # ── Labels das UFs ────────────────────────────────────────────────────
    c.setFont("Helvetica", 5.5); c.setFillColor(colors.HexColor("#555555"))
    for uf, (lon, lat) in CENTROIDES_UF.items():
        px, py = _lon_lat_para_canvas(lon, lat, bbox, map_x, map_y, map_w, map_h)
        if map_x <= px <= map_x+map_w and map_y <= py <= map_y+map_h:
            c.drawCentredString(px, py, uf)

    # ── Pins dos ministros ────────────────────────────────────────────────
    def carregar_foto(ministerio):
        if not pasta_fotos or not os.path.isdir(pasta_fotos):
            return None
        for ext in ['.jpg','.jpeg','.png','.JPG','.JPEG','.PNG']:
            path = os.path.join(pasta_fotos, ministerio+ext)
            if os.path.exists(path): 
                with open(path,'rb') as f: return f.read()
        nome = re.sub(r'[^a-zA-Z0-9\-_]', '_', ministerio)
        for ext in ['.jpg','.jpeg','.png']:
            path = os.path.join(pasta_fotos, nome+ext)
            if os.path.exists(path):
                with open(path,'rb') as f: return f.read()
        return None

    pins_pos = {}
    for d in destinos:
        tipo, local, min_nome = d['tipo'], d['local'], d['ministerio']
        if tipo == 'estado':
            coords = CENTROIDES_UF.get(local)
        else:
            coords = CENTROIDES_PAISES.get(local)
        if not coords:
            continue

        lon, lat = coords
        px, py = _lon_lat_para_canvas(lon, lat, bbox, map_x, map_y, map_w, map_h)

        # Desviar se sobreposição
        chave = f"{round(px/10)},{round(py/10)}"
        offset = 0
        while f"{chave}_{offset}" in pins_pos:
            offset += 1
            px += 8*mm
        pins_pos[f"{chave}_{offset}"] = True

        # Label do país (fora do Brasil)
        if tipo == 'pais':
            c.setFont("Helvetica", 6.5); c.setFillColor(PRETO)
            c.drawCentredString(px, py-20*mm, local)

        desenhar_pin(c, px, py, carregar_foto(min_nome), raio_mm=6.5)

    # ── Logo Gov.BR no rodapé ─────────────────────────────────────────────
    logo_y = 8*mm
    c.setFont("Helvetica-Bold", 7); c.setFillColor(PRETO)
    c.drawCentredString(PW/2, logo_y+12*mm, "GOVERNO DO")
    letras = [("B","#4FAE32"),("R","#E52521"),("A","#1A1A1A"),
              ("S","#FFD008"),("I","#3253A0"),("L","#4FAE32")]
    c.setFont("Helvetica-Bold", 13)
    sx = PW/2 - len(letras)*4.5
    for letra, cor in letras:
        c.setFillColor(colors.HexColor(cor))
        c.drawString(sx, logo_y+3*mm, letra)
        sx += 9
    c.setFont("Helvetica", 6); c.setFillColor(colors.HexColor("#555555"))
    c.drawCentredString(PW/2, logo_y-1*mm, "DO LADO DO POVO BRASILEIRO")


# Coordenadas reais dos estados (embutidas — sem dependência de URL)
_ESTADOS_POLIGONOS = {
"AC":[(-73.2,-10.1),(-72.4,-9.5),(-71.0,-9.0),(-70.6,-9.8),(-70.3,-11.1),(-69.8,-11.1),(-70.5,-10.9),(-71.2,-10.1),(-73.2,-10.1)],
"AL":[(-37.2,-8.6),(-36.4,-9.1),(-35.6,-9.5),(-35.1,-8.9),(-35.2,-8.3),(-36.0,-7.7),(-37.3,-8.1),(-37.2,-8.6)],
"AM":[(-73.8,-7.3),(-73.1,-6.0),(-72.9,-4.2),(-71.4,-4.4),(-70.0,-4.2),(-69.9,-1.7),(-68.0,-2.0),(-67.3,-2.9),(-65.3,-3.1),(-64.2,-4.2),(-62.0,-4.0),(-60.2,-4.5),(-59.9,-4.4),(-60.5,-2.5),(-59.9,-1.2),(-60.4,0.5),(-58.4,1.5),(-55.0,-0.1),(-52.5,-0.5),(-52.3,-7.4),(-53.3,-7.5),(-73.8,-7.3)],
"AP":[(-51.9,4.4),(-50.8,4.3),(-49.9,1.2),(-50.4,0.5),(-52.0,0.2),(-51.5,-0.2),(-52.2,-0.4),(-52.8,0.2),(-51.9,4.4)],
"BA":[(-46.6,-8.5),(-42.5,-9.0),(-38.5,-9.5),(-37.3,-10.5),(-37.0,-11.4),(-37.8,-12.8),(-38.5,-13.6),(-39.2,-15.2),(-39.8,-17.8),(-40.7,-18.4),(-44.0,-17.5),(-46.0,-16.2),(-47.2,-14.0),(-46.0,-13.5),(-46.3,-11.5),(-46.6,-8.5)],
"CE":[(-41.4,-2.8),(-40.0,-2.8),(-37.3,-4.8),(-34.9,-7.0),(-37.6,-7.9),(-40.0,-7.4),(-41.4,-4.5),(-41.4,-2.8)],
"DF":[(-48.3,-15.5),(-47.3,-15.5),(-47.3,-16.1),(-48.3,-16.1),(-48.3,-15.5)],
"ES":[(-41.9,-17.9),(-40.0,-18.5),(-39.6,-19.5),(-39.8,-21.3),(-41.5,-20.5),(-41.9,-17.9)],
"GO":[(-53.3,-12.6),(-50.0,-13.0),(-47.2,-13.0),(-46.5,-14.2),(-46.0,-16.2),(-47.4,-17.9),(-49.5,-18.8),(-51.6,-18.5),(-52.9,-15.5),(-53.3,-12.6)],
"MA":[(-48.6,-1.0),(-44.5,-1.2),(-41.8,-2.8),(-43.3,-5.8),(-44.8,-7.0),(-46.5,-7.5),(-47.5,-8.5),(-47.0,-9.5),(-46.0,-10.3),(-48.6,-8.5),(-48.6,-1.0)],
"MG":[(-51.1,-14.2),(-47.5,-14.2),(-46.5,-15.8),(-44.5,-16.0),(-44.0,-17.5),(-42.5,-19.5),(-41.5,-20.5),(-41.5,-22.9),(-44.5,-23.2),(-47.0,-22.5),(-51.1,-19.5),(-51.1,-14.2)],
"MS":[(-58.2,-17.2),(-54.3,-17.5),(-52.9,-20.0),(-51.0,-21.5),(-52.0,-22.5),(-54.5,-24.0),(-58.2,-22.0),(-58.2,-17.2)],
"MT":[(-61.6,-7.4),(-58.0,-8.0),(-54.5,-9.5),(-50.2,-10.0),(-50.3,-14.0),(-52.9,-15.5),(-54.3,-17.5),(-58.2,-17.2),(-60.0,-16.0),(-61.6,-13.5),(-61.6,-7.4)],
"PA":[(-58.5,-0.1),(-54.5,-0.5),(-52.5,-0.5),(-52.3,-7.4),(-54.9,-8.5),(-57.8,-8.2),(-60.4,-7.5),(-60.2,-4.5),(-58.5,-0.1)],
"PB":[(-38.8,-6.0),(-36.5,-6.5),(-34.8,-6.5),(-34.9,-8.4),(-37.5,-8.1),(-38.4,-7.3),(-38.8,-6.0)],
"PE":[(-41.4,-7.2),(-37.3,-7.9),(-34.8,-7.0),(-34.9,-8.4),(-36.5,-9.0),(-38.3,-9.5),(-41.4,-9.5),(-41.4,-7.2)],
"PI":[(-45.9,-2.8),(-43.3,-2.8),(-41.4,-2.8),(-41.4,-7.2),(-43.5,-7.5),(-44.8,-7.0),(-46.5,-7.5),(-45.9,-2.8)],
"PR":[(-54.6,-22.5),(-51.0,-22.5),(-48.5,-23.8),(-48.0,-25.5),(-53.2,-26.2),(-54.6,-24.0),(-54.6,-22.5)],
"RJ":[(-44.9,-21.0),(-43.0,-22.0),(-41.0,-21.5),(-40.9,-22.5),(-43.5,-23.4),(-44.9,-23.0),(-44.9,-21.0)],
"RN":[(-38.6,-4.8),(-35.0,-4.8),(-34.9,-5.8),(-35.2,-6.9),(-37.5,-6.5),(-38.6,-6.0),(-38.6,-4.8)],
"RO":[(-66.8,-7.9),(-63.5,-7.4),(-60.4,-7.5),(-59.8,-10.0),(-63.0,-12.5),(-65.4,-13.5),(-66.8,-10.5),(-66.8,-7.9)],
"RR":[(-64.8,5.3),(-60.0,5.3),(-58.9,3.5),(-59.8,2.0),(-60.5,-0.2),(-63.5,-0.2),(-64.8,2.0),(-64.8,5.3)],
"RS":[(-57.6,-27.1),(-53.4,-27.5),(-50.0,-28.5),(-49.7,-32.0),(-51.5,-33.8),(-53.5,-33.7),(-57.6,-30.0),(-57.6,-27.1)],
"SC":[(-53.9,-25.9),(-50.0,-25.9),(-48.3,-26.5),(-48.5,-29.4),(-50.5,-28.8),(-53.9,-27.5),(-53.9,-25.9)],
"SE":[(-38.3,-9.5),(-37.0,-9.5),(-36.4,-10.0),(-36.5,-11.6),(-38.0,-11.0),(-38.3,-9.5)],
"SP":[(-53.1,-19.8),(-47.0,-19.8),(-44.5,-23.2),(-44.9,-23.4),(-48.0,-25.5),(-53.1,-24.0),(-53.1,-19.8)],
"TO":[(-50.7,-5.2),(-47.5,-5.8),(-46.0,-6.0),(-46.5,-10.5),(-48.0,-12.5),(-50.0,-13.0),(-50.7,-9.0),(-50.7,-5.2)],
}

def _desenhar_brasil_fallback(c, bbox, ox, oy, mw, mh, estados_visitados):
    """Desenha estados com polígonos reais embutidos no código."""
    for uf, ring in _ESTADOS_POLIGONOS.items():
        pts = _polygon_to_pts(ring, bbox, mw, mh)
        pts_canvas = [(ox + x, oy + mh - y) for x, y in pts]
        cor = colors.HexColor("#AAAACC") if uf in estados_visitados else CINZA_ESTADO
        _draw_polygon(c, pts_canvas, cor, CINZA_BORDA, lw=0.6)    # ── Bbox fixo no Brasil ──────────────────────────────────────────────
    bbox = (-74, -34, -28, 6)

    # ── Baixar e desenhar GeoJSON ─────────────────────────────────────────
    geojson_mundo  = _baixar_geojson(GEOJSON_MUNDO)
    geojson_brasil = _baixar_geojson(GEOJSON_BRASIL)

    if geojson_mundo:
        for feat in geojson_mundo.get('features', []):
            props = feat.get('properties', {})
            nome_pais = props.get('ADMIN', props.get('name', ''))
            cor = colors.HexColor("#AAAACC") if nome_pais in paises_visitados else CINZA_PAIS
            _draw_feature(c, feat, bbox, map_x, map_y, map_w, map_h, cor)

    if geojson_brasil:
        for feat in geojson_brasil.get('features', []):
            props = feat.get('properties', {})
            sigla = props.get('sigla', props.get('UF', props.get('abbrev', '')))
            cor = colors.HexColor("#AAAACC") if sigla in estados_visitados else CINZA_ESTADO
            _draw_feature(c, feat, bbox, map_x, map_y, map_w, map_h, cor)
    else:
        _desenhar_brasil_fallback(c, bbox, map_x, map_y, map_w, map_h, estados_visitados)

    # ── Bloco "ONDE estamos" ─────────────────────────────────────────────
    bx = map_x; by = map_y + map_h*0.38; bw = 42*mm; bh = 28*mm
    c.setFillColor(VERDE_MEDIO)
    c.rect(bx, by, bw, bh, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 22); c.setFillColor(AMARELO)
    c.drawString(bx+4*mm, by+17*mm, "ONDE")
    c.setFont("Helvetica-BoldOblique", 14); c.setFillColor(BRANCO)
    c.drawString(bx+4*mm, by+6*mm, "estamos")
    c.setFillColor(VERDE_MEDIO)
    c.rect(PW-MARGIN-8*mm, by, 8*mm, bh, fill=1, stroke=0)

    # ── Labels das UFs ────────────────────────────────────────────────────
    c.setFont("Helvetica", 5.5); c.setFillColor(colors.HexColor("#555555"))
    for uf, (lon, lat) in CENTROIDES_UF.items():
        px, py = _lon_lat_para_canvas(lon, lat, bbox, map_x, map_y, map_w, map_h)
        if map_x <= px <= map_x+map_w and map_y <= py <= map_y+map_h:
            c.drawCentredString(px, py, uf)

    # ── Pins dos ministros ────────────────────────────────────────────────
    # Países internacionais: posições fixas no lado direito do mapa
    POSICOES_INT = [
        (map_x + map_w*0.88, map_y + map_h*0.90),
        (map_x + map_w*0.88, map_y + map_h*0.75),
        (map_x + map_w*0.88, map_y + map_h*0.60),
        (map_x + map_w*0.88, map_y + map_h*0.45),
        (map_x + map_w*0.75, map_y + map_h*0.90),
        (map_x + map_w*0.75, map_y + map_h*0.75),
    ]
    idx_int = 0
    pins_pos = {}

    for d in destinos:
        tipo, local, min_nome = d['tipo'], d['local'], d['ministerio']

        if tipo == 'estado':
            coords = CENTROIDES_UF.get(local)
            if not coords: continue
            lon, lat = coords
            px, py = _lon_lat_para_canvas(lon, lat, bbox, map_x, map_y, map_w, map_h)
            chave = f"{round(px/10)},{round(py/10)}"
            offset = 0
            while f"{chave}_{offset}" in pins_pos:
                offset += 1; px += 9*mm
            pins_pos[f"{chave}_{offset}"] = True
        else:
            if idx_int >= len(POSICOES_INT): continue
            px, py = POSICOES_INT[idx_int]; idx_int += 1
            c.setFont("Helvetica-Bold", 6.5); c.setFillColor(PRETO)
            c.drawCentredString(px, py - 19*mm, local)

        desenhar_pin(c, px, py, carregar_foto(min_nome), raio_mm=6.5)

    # ── Logo Gov.BR no rodapé ─────────────────────────────────────────────
    logo_y = 8*mm
    c.setFont("Helvetica-Bold", 7); c.setFillColor(PRETO)
    c.drawCentredString(PW/2, logo_y+12*mm, "GOVERNO DO")
    letras = [("B","#4FAE32"),("R","#E52521"),("A","#1A1A1A"),
              ("S","#FFD008"),("I","#3253A0"),("L","#4FAE32")]
    c.setFont("Helvetica-Bold", 13)
    sx = PW/2 - len(letras)*4.5
    for letra, cor in letras:
        c.setFillColor(colors.HexColor(cor))
        c.drawString(sx, logo_y+3*mm, letra)
        sx += 9
    c.setFont("Helvetica", 6); c.setFillColor(colors.HexColor("#555555"))
    c.drawCentredString(PW/2, logo_y-1*mm, "DO LADO DO POVO BRASILEIRO")


# Coordenadas reais dos estados (embutidas — sem dependência de URL)
_ESTADOS_POLIGONOS = {
"AC":[(-73.2,-10.1),(-72.4,-9.5),(-71.0,-9.0),(-70.6,-9.8),(-70.3,-11.1),(-69.8,-11.1),(-70.5,-10.9),(-71.2,-10.1),(-73.2,-10.1)],
"AL":[(-37.2,-8.6),(-36.4,-9.1),(-35.6,-9.5),(-35.1,-8.9),(-35.2,-8.3),(-36.0,-7.7),(-37.3,-8.1),(-37.2,-8.6)],
"AM":[(-73.8,-7.3),(-73.1,-6.0),(-72.9,-4.2),(-71.4,-4.4),(-70.0,-4.2),(-69.9,-1.7),(-68.0,-2.0),(-67.3,-2.9),(-65.3,-3.1),(-64.2,-4.2),(-62.0,-4.0),(-60.2,-4.5),(-59.9,-4.4),(-60.5,-2.5),(-59.9,-1.2),(-60.4,0.5),(-58.4,1.5),(-55.0,-0.1),(-52.5,-0.5),(-52.3,-7.4),(-53.3,-7.5),(-73.8,-7.3)],
"AP":[(-51.9,4.4),(-50.8,4.3),(-49.9,1.2),(-50.4,0.5),(-52.0,0.2),(-51.5,-0.2),(-52.2,-0.4),(-52.8,0.2),(-51.9,4.4)],
"BA":[(-46.6,-8.5),(-42.5,-9.0),(-38.5,-9.5),(-37.3,-10.5),(-37.0,-11.4),(-37.8,-12.8),(-38.5,-13.6),(-39.2,-15.2),(-39.8,-17.8),(-40.7,-18.4),(-44.0,-17.5),(-46.0,-16.2),(-47.2,-14.0),(-46.0,-13.5),(-46.3,-11.5),(-46.6,-8.5)],
"CE":[(-41.4,-2.8),(-40.0,-2.8),(-37.3,-4.8),(-34.9,-7.0),(-37.6,-7.9),(-40.0,-7.4),(-41.4,-4.5),(-41.4,-2.8)],
"DF":[(-48.3,-15.5),(-47.3,-15.5),(-47.3,-16.1),(-48.3,-16.1),(-48.3,-15.5)],
"ES":[(-41.9,-17.9),(-40.0,-18.5),(-39.6,-19.5),(-39.8,-21.3),(-41.5,-20.5),(-41.9,-17.9)],
"GO":[(-53.3,-12.6),(-50.0,-13.0),(-47.2,-13.0),(-46.5,-14.2),(-46.0,-16.2),(-47.4,-17.9),(-49.5,-18.8),(-51.6,-18.5),(-52.9,-15.5),(-53.3,-12.6)],
"MA":[(-48.6,-1.0),(-44.5,-1.2),(-41.8,-2.8),(-43.3,-5.8),(-44.8,-7.0),(-46.5,-7.5),(-47.5,-8.5),(-47.0,-9.5),(-46.0,-10.3),(-48.6,-8.5),(-48.6,-1.0)],
"MG":[(-51.1,-14.2),(-47.5,-14.2),(-46.5,-15.8),(-44.5,-16.0),(-44.0,-17.5),(-42.5,-19.5),(-41.5,-20.5),(-41.5,-22.9),(-44.5,-23.2),(-47.0,-22.5),(-51.1,-19.5),(-51.1,-14.2)],
"MS":[(-58.2,-17.2),(-54.3,-17.5),(-52.9,-20.0),(-51.0,-21.5),(-52.0,-22.5),(-54.5,-24.0),(-58.2,-22.0),(-58.2,-17.2)],
"MT":[(-61.6,-7.4),(-58.0,-8.0),(-54.5,-9.5),(-50.2,-10.0),(-50.3,-14.0),(-52.9,-15.5),(-54.3,-17.5),(-58.2,-17.2),(-60.0,-16.0),(-61.6,-13.5),(-61.6,-7.4)],
"PA":[(-58.5,-0.1),(-54.5,-0.5),(-52.5,-0.5),(-52.3,-7.4),(-54.9,-8.5),(-57.8,-8.2),(-60.4,-7.5),(-60.2,-4.5),(-58.5,-0.1)],
"PB":[(-38.8,-6.0),(-36.5,-6.5),(-34.8,-6.5),(-34.9,-8.4),(-37.5,-8.1),(-38.4,-7.3),(-38.8,-6.0)],
"PE":[(-41.4,-7.2),(-37.3,-7.9),(-34.8,-7.0),(-34.9,-8.4),(-36.5,-9.0),(-38.3,-9.5),(-41.4,-9.5),(-41.4,-7.2)],
"PI":[(-45.9,-2.8),(-43.3,-2.8),(-41.4,-2.8),(-41.4,-7.2),(-43.5,-7.5),(-44.8,-7.0),(-46.5,-7.5),(-45.9,-2.8)],
"PR":[(-54.6,-22.5),(-51.0,-22.5),(-48.5,-23.8),(-48.0,-25.5),(-53.2,-26.2),(-54.6,-24.0),(-54.6,-22.5)],
"RJ":[(-44.9,-21.0),(-43.0,-22.0),(-41.0,-21.5),(-40.9,-22.5),(-43.5,-23.4),(-44.9,-23.0),(-44.9,-21.0)],
"RN":[(-38.6,-4.8),(-35.0,-4.8),(-34.9,-5.8),(-35.2,-6.9),(-37.5,-6.5),(-38.6,-6.0),(-38.6,-4.8)],
"RO":[(-66.8,-7.9),(-63.5,-7.4),(-60.4,-7.5),(-59.8,-10.0),(-63.0,-12.5),(-65.4,-13.5),(-66.8,-10.5),(-66.8,-7.9)],
"RR":[(-64.8,5.3),(-60.0,5.3),(-58.9,3.5),(-59.8,2.0),(-60.5,-0.2),(-63.5,-0.2),(-64.8,2.0),(-64.8,5.3)],
"RS":[(-57.6,-27.1),(-53.4,-27.5),(-50.0,-28.5),(-49.7,-32.0),(-51.5,-33.8),(-53.5,-33.7),(-57.6,-30.0),(-57.6,-27.1)],
"SC":[(-53.9,-25.9),(-50.0,-25.9),(-48.3,-26.5),(-48.5,-29.4),(-50.5,-28.8),(-53.9,-27.5),(-53.9,-25.9)],
"SE":[(-38.3,-9.5),(-37.0,-9.5),(-36.4,-10.0),(-36.5,-11.6),(-38.0,-11.0),(-38.3,-9.5)],
"SP":[(-53.1,-19.8),(-47.0,-19.8),(-44.5,-23.2),(-44.9,-23.4),(-48.0,-25.5),(-53.1,-24.0),(-53.1,-19.8)],
"TO":[(-50.7,-5.2),(-47.5,-5.8),(-46.0,-6.0),(-46.5,-10.5),(-48.0,-12.5),(-50.0,-13.0),(-50.7,-9.0),(-50.7,-5.2)],
}

def _desenhar_brasil_fallback(c, bbox, ox, oy, mw, mh, estados_visitados):
    """Desenha estados com polígonos reais embutidos no código."""
    for uf, ring in _ESTADOS_POLIGONOS.items():
        pts = _polygon_to_pts(ring, bbox, mw, mh)
        pts_canvas = [(ox + x, oy + mh - y) for x, y in pts]
        cor = colors.HexColor("#AAAACC") if uf in estados_visitados else CINZA_ESTADO
        _draw_polygon(c, pts_canvas, cor, CINZA_BORDA, lw=0.6)
