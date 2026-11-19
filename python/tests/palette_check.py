import sys, math
def lin(c): c/=255; return c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4
def hex2(h): h=h.lstrip('#'); return [int(h[i:i+2],16) for i in (0,2,4)]
def oklab(rgb):
    r,g,b=rgb
    l=0.4122214708*r+0.5363325363*g+0.0514459929*b; m=0.2119034982*r+0.6806995451*g+0.1073969566*b; s=0.0883024619*r+0.2817188376*g+0.6299787005*b
    l,m,s=[x**(1/3) for x in (l,m,s)]
    return (0.2104542553*l+0.7936177850*m-0.0040720468*s, 1.9779984951*l-2.4285922050*m+0.4505937099*s, 0.0259040371*l+0.7827717662*m-0.8086757660*s)
M={'protan':[[0.152286,1.052583,-0.204868],[0.114503,0.786281,0.099216],[-0.003882,-0.048116,1.051998]],
   'deutan':[[0.367322,0.860646,-0.227968],[0.280085,0.672501,0.047413],[-0.011820,0.042940,0.968881]],
   'tritan':[[1.255528,-0.076749,-0.178779],[-0.078411,0.930809,0.147602],[0.004733,0.691367,0.303900]]}
def sim(rgb,k): return [max(0,min(1,sum(M[k][i][j]*rgb[j] for j in range(3)))) for i in range(3)]
def dE(a,b): A,B=oklab(a),oklab(b); return 100*math.dist(A,B)
def lum(rgb): return 0.2126*rgb[0]+0.7152*rgb[1]+0.0722*rgb[2]
def contrast(a,b): la,lb=sorted([lum(a),lum(b)],reverse=True); return (la+0.05)/(lb+0.05)
pal=sys.argv[1].split(','); surf=[lin(c) for c in hex2(sys.argv[2])]
L=[[lin(c) for c in hex2(h)] for h in pal]
print(f'surface {sys.argv[2]}')
for h,c in zip(pal,L): print(f'  {h}  contrast vs surface {contrast(c,surf):.2f}  OKLab L {oklab(c)[0]:.2f}')
worst_n=worst_c=999
for i in range(len(pal)-1):
    a,b=L[i],L[i+1]; n=dE(a,b); c=min(dE(sim(a,k),sim(b,k)) for k in M); worst_n=min(worst_n,n); worst_c=min(worst_c,c)
    print(f'  adjacent {pal[i]}-{pal[i+1]}: normal dE {n:5.1f} (>=15)  worst CVD dE {c:5.1f} (>=8 target)  {"PASS" if n>=15 and c>=8 else ("WARN" if n>=15 and c>=6 else "FAIL")}')
a,b=hex2('#22c3e6'),hex2('#14b8a6'); a=[lin(x) for x in a]; b=[lin(x) for x in b]
print(f'  for reference cyan vs teal: normal dE {dE(a,b):.1f}, worst CVD dE {min(dE(sim(a,k),sim(b,k)) for k in M):.1f}')
print(f'WORST adjacent: normal {worst_n:.1f}, CVD {worst_c:.1f}')
