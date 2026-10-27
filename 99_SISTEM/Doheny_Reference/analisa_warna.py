import sys, json
from pathlib import Path
REF = Path(__file__).resolve().parent
sys.path.insert(0, str(REF.parent / 'pydeps'))
from PIL import Image, ImageStat
ROOT = REF.parents[1]
t = Image.open(ROOT / '02_PRODUK/Nakas/Doheny_B_Tan_Mindi/Tekstur/B_Tan_Mindi_Asli.png').convert('RGB')
w, h = t.size
out = {'size': [w, h], 'mean': ImageStat.Stat(t).mean, 'std': ImageStat.Stat(t).stddev}
for k, box in {'top': (0, 0, w, 20), 'bottom': (0, h - 20, w, h), 'left': (0, 0, 20, h), 'right': (w - 20, 0, w, h), 'center': (w // 4, h // 4, 3 * w // 4, 3 * h // 4)}.items():
    out[k] = [round(v) for v in ImageStat.Stat(t.crop(box)).mean]
r = Image.open(ROOT / '04_HASIL_RENDER/Doheny_B_Tan_Mindi/hero_finish_check.png').convert('RGB')
rw, rh = r.size
# sample the drawer front / side regions roughly (centre band)
out['render_center'] = [round(v) for v in ImageStat.Stat(r.crop((rw // 3, rh // 3, 2 * rw // 3, 2 * rh // 3))).mean]
# PDF page 2 swatch: left half is B TAN-MINDY per pdf_text ordering
p = Image.open(REF / 'pdf_page_2.png').convert('RGB')
pw, ph = p.size
for k, box in {'pdf_left': (int(pw * .08), int(ph * .15), int(pw * .45), int(ph * .85)), 'pdf_right': (int(pw * .55), int(ph * .15), int(pw * .92), int(ph * .85))}.items():
    out[k] = [round(v) for v in ImageStat.Stat(p.crop(box)).mean]
t.resize((376, 565)).save(REF / 'tex_preview.png')
p.save(REF / 'pdf_page_2_check.png')
print('ANALISA', json.dumps(out))
