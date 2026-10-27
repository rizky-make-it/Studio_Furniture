import sys,json
from pathlib import Path
BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE.parent/'pydeps'))
import fitz,ezdxf
pdf=fitz.open(r'C:/Users/Admin/Downloads/ZUMA GROUP.pdf')
texts=[];matches=[]
for i,p in enumerate(pdf):
    t=p.get_text();texts.append(f'\n--- PAGE {i+1} ---\n'+t)
    if any(k in t.lower() for k in ['mindi','doheny','tan']):
        matches.append({'page':i+1,'text':t})
        p.get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(str(BASE/f'pdf_page_{i+1}.png'))
(BASE/'pdf_text.txt').write_text(''.join(texts),encoding='utf-8')
print('PDF_PAGES',len(pdf));print('PDF_MATCHES',json.dumps(matches))
doc=ezdxf.readfile(BASE/'doheny.dxf')
print('UNITS',doc.units,'EXTENTS',str(doc.header.get('$EXTMIN')),str(doc.header.get('$EXTMAX')))
out=[]
def scan(entities,depth=0):
    for e in entities:
        if e.dxftype()=='INSERT':
            out.append({'type':'INSERT','name':e.dxf.name,'pos':list(e.dxf.insert),'scale':[e.dxf.xscale,e.dxf.yscale,e.dxf.zscale]})
            if depth<8:scan(e.virtual_entities(),depth+1)
        elif e.dxftype() in ['TEXT','MTEXT','DIMENSION']:
            out.append({'type':e.dxftype(),'data':{k:str(v) for k,v in e.dxf.all_existing_dxf_attribs().items()}})
scan(doc.modelspace())
(BASE/'cad_details.json').write_text(json.dumps(out,indent=2))
print('CAD_LABELS',json.dumps(out))
