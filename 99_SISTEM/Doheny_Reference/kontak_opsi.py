import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '99_SISTEM/pydeps'))
from PIL import Image, ImageDraw
d = ROOT / '04_HASIL_RENDER/Doheny_B_Tan_Mindi/OPSI_cek'
files = sorted(d.glob('opsi_*.png'))
ims = [Image.open(f).convert('RGB').resize((420, 420)) for f in files]
sheet = Image.new('RGB', (420 * len(ims), 450), (30, 30, 30))
dr = ImageDraw.Draw(sheet)
for i, (im, f) in enumerate(zip(ims, files)):
    sheet.paste(im, (420 * i, 30)); dr.text((420 * i + 8, 8), f.stem, fill=(255, 255, 255))
sheet.save(d / 'kontak.png'); print('KONTAK_OK')
