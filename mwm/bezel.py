# SPDX-License-Identifier: MIT
"""Generate a bezel output shader from the current monitor inventory."""
import hashlib,json,math
from span_display_info import logical_rect,union_bounds

def display_plan(outputs,gap):
    if not math.isfinite(gap) or not 0<=gap<=100:raise ValueError('Invalid bezel width')
    screens=sorted([o for o in outputs if o.get('enabled') and o.get('connected')],key=lambda o:logical_rect(o)[0])
    bounds=union_bounds(screens);rows=[];offset=0.;height=max(float(o['physical_mm'][1]) for o in screens if o.get('physical_mm'))
    previous=None
    for o in screens:
        mm=o.get('physical_mm')
        if not mm or any(not math.isfinite(float(v)) or float(v)<=0 for v in mm):raise ValueError('Monitor physical dimensions unavailable')
        x,y,w,h=logical_rect(o)
        if abs(y+h-(bounds['y']+bounds['height']))>2:raise ValueError('Bottom-align monitors in Plasma before enabling bezel compensation')
        if previous is not None and abs(x-previous)>2:raise ValueError('Only side-by-side monitors are supported')
        rows.append(dict(name=o['name'],logical=[x-bounds['x'],y-bounds['y'],w,h],physical=[offset,height-float(mm[1]),float(mm[0]),float(mm[1])]))
        offset+=float(mm[0])+gap;previous=x+w
    return dict(bounds=bounds,screens=rows,width_mm=offset-gap,height_mm=height,gap_mm=gap)

def fingerprint(plan):return hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()[:16]

def shader(plan):
    # Keep the uniform block nonempty: a zero-sized UBO crashed this driver.
    code='''uniform float MWMEnabled = 1.0;
texture MWMBackBuffer : COLOR;
sampler MWMColor { Texture=MWMBackBuffer; MinFilter=LINEAR; MagFilter=LINEAR; AddressU=CLAMP; AddressV=CLAMP; };
texture MWMCopyTexture { Width=BUFFER_WIDTH; Height=BUFFER_HEIGHT; Format=RGBA8; };
sampler MWMCopy { Texture=MWMCopyTexture; MinFilter=LINEAR; MagFilter=LINEAR; AddressU=CLAMP; AddressV=CLAMP; };
void MWMVertex(uint id:SV_VertexID,out float4 pos:SV_Position,out float2 uv:TEXCOORD) {
 uv=float2((id<<1)&2,id&2);pos=float4(uv*float2(2,-2)+float2(-1,1),0,1);
}
float4 MWMCopyPixel(float4 pos:SV_Position,float2 uv:TEXCOORD):SV_Target { return tex2D(MWMColor,uv); }
float4 MWMPixel(float4 pos:SV_Position,float2 uv:TEXCOORD):SV_Target {
 if(MWMEnabled<0.5)return tex2D(MWMCopy,uv);
'''
    b=plan['bounds'];code+=f" float2 logical=uv*float2({b['width']:.9f},{b['height']:.9f});\n float2 mm=float2(-1,-1);\n"
    for row in plan['screens']:
        x,y,w,h=row['logical'];mx,my,mw,mh=row['physical']
        code+=f' if(logical.x>={x:.9f} && logical.x<{x+w:.9f} && logical.y>={y:.9f} && logical.y<{y+h:.9f}) mm=float2({mx:.9f},{my:.9f})+(logical-float2({x:.9f},{y:.9f}))/float2({w:.9f},{h:.9f})*float2({mw:.9f},{mh:.9f});\n'
    code+=f" float2 canvas=float2({plan['width_mm']:.9f},{plan['height_mm']:.9f});\n"
    return code+''' float aspect=float(BUFFER_WIDTH)/float(BUFFER_HEIGHT);
 float2 fitted=float2(min(canvas.x,canvas.y*aspect),min(canvas.y,canvas.x/aspect));
 float2 src=(mm-(canvas-fitted)*0.5)/fitted;
 if(src.x<0 || src.y<0 || src.x>1 || src.y>1)return float4(0,0,0,1);
 return tex2D(MWMCopy,src);
}
technique MWMBezel {
 pass CopySource { VertexShader=MWMVertex; PixelShader=MWMCopyPixel; RenderTarget=MWMCopyTexture; }
 pass BezelOutput { VertexShader=MWMVertex; PixelShader=MWMPixel; }
}
'''
