"""Deterministic source-to-crop bookkeeping; no learned or answer-aware operator."""
import math

from PIL import Image, ImageDraw, ImageFont

COLORS = ['#e03030', '#0055df']


def letterbox(image, side):
    scale = side / max(image.size)
    size = tuple(max(1, round(v*scale)) for v in image.size)
    offset = ((side-size[0])//2, (side-size[1])//2)
    canvas = Image.new('RGB', (side, side), 'white')
    canvas.paste(image.resize(size, Image.Resampling.LANCZOS), offset)
    return canvas, {'size':list(size), 'offset':list(offset), 'source_size':list(image.size), 'side':side}


def regions(parsed, image):
    _, transform = letterbox(image, 1024)
    output, audit = [], []
    proposed = parsed.get('regions', []) if isinstance(parsed, dict) else []
    if not isinstance(proposed, list):
        proposed = []
    for item in proposed[:2]:
        try:
            b = item['box']
            assert isinstance(b, list) and len(b)==4
            assert all(isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v) and 0<=v<=1000 for v in b)
            x0,y0,x1,y1 = [v*1024/1000 for v in b]
            assert x0<x1 and y0<y1
            w,h = transform['size'];ox,oy=transform['offset'];sw,sh=image.size
            box = [max(0,math.floor((x0-ox)*sw/w+1e-8)),max(0,math.floor((y0-oy)*sh/h+1e-8)),
                   min(sw,math.ceil((x1-ox)*sw/w-1e-8)),min(sh,math.ceil((y1-oy)*sh/h-1e-8))]
            assert box[2]-box[0]>=8 and box[3]-box[1]>=8
            output.append({'id':str(len(output)+1),'description':str(item.get('description',''))[:250], 'source_box':box, 'supported':True})
            audit.append({'status':'valid_source_address','input_box':b,'source_box':box})
        except (KeyError,ValueError,TypeError,AssertionError,OverflowError):
            audit.append({'status':'unsupported_address'})
    while len(output)<2:
        output.append({'id':str(len(output)+1),'description':'No supported ROI; unmodified full-image fallback',
                       'source_box':[0,0,*image.size], 'supported':False})
    return output, audit


def views(image, chosen, linked=False, shuffled=False):
    overview, t = letterbox(image, 1024)
    crops = [letterbox(image.crop(r['source_box']),768)[0] for r in chosen]
    if linked:
        draw = ImageDraw.Draw(overview)
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',24)
        for i,r in enumerate(chosen):
            if not r['supported']:
                continue
            sw,sh=image.size;w,h=t['size'];ox,oy=t['offset']
            x0,y0,x1,y1=r['source_box'];b=[x0*w/sw+ox,y0*h/sh+oy,x1*w/sw+ox,y1*h/sh+oy]
            draw.rectangle(b,outline=COLORS[i],width=3)
            x,y=b[:2];y=max(0,y-31)
            draw.rectangle([x,y,min(1023,x+35),y+30],fill=COLORS[i])
            draw.text((x+7,y),str(i+1),fill='white',font=font)
    if shuffled:
        crops.reverse()
    return [overview,*crops]


def correspondence(chosen):
    return [{'image_index':i+2,'overview_rectangle':r['id'],'source_box_pixels':r['source_box'],
             'address_supported':r['supported']} for i,r in enumerate(chosen)]
