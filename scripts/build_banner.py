"""Locally generate the profile hero from a provided illustrated backdrop.

Pillow is a build-time dependency only. The finished README uses a plain PNG.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "assets" / "hero-background.png"
OUTPUT = ROOT / "assets" / "hero.png"

image = Image.open(INPUT).convert("RGB")
if image.size != (2172,724):
    image = image.resize((2172, 724), Image.Resampling.LANCZOS)
w,h = image.size
px = image.load()
# Reinforce the dark area for legible wordmark on narrow rendered GitHub profiles.
for x in range(int(w*.65)):
    opacity = .42 * (1 - (x / (w*.65))) ** 1.35
    for y in range(h):
        r,g,b=px[x,y]
        px[x,y]=(int(r*(1-opacity)+2*opacity),int(g*(1-opacity)+9*opacity),int(b*(1-opacity)+19*opacity))

d = ImageDraw.Draw(image)
def font(name,size):
    return ImageFont.truetype(name,size)
main = font('/usr/share/fonts/truetype/roboto/unhinted/RobotoCondensed-Bold.ttf', 170)
label = font('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 30)
sub = font('/usr/share/fonts/truetype/lato/Lato-Medium.ttf', 43)
small=font('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 25)
# Accent device, spacing chosen to survive GitHub's ~850px viewport image scaling.
d.rounded_rectangle((112,117,156,127), radius=4, fill='#38D6FF')
d.text((177,97), 'BUILDING SYSTEMS BEYOND PLATFORMS', font=label, fill='#86CCDA', stroke_width=0)
d.text((105,230),'CROWETIC',font=main,fill='#EDF9FF',stroke_width=0)
d.rectangle((113,438,892,442), fill='#0D647D')
d.rectangle((113,438,360,443), fill='#34D9FD')
d.text((112,479), 'Decentralized systems  /  AI infrastructure', font=sub,fill='#E1F3F7')
d.text((114,624), 'QORTAL  •  NUQLOUD  •  OPEN INFRASTRUCTURE', font=small,fill='#85B9CC')
image.save(OUTPUT, optimize=True)
print(OUTPUT, OUTPUT.stat().st_size)
