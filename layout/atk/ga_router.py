#!/usr/bin/env python3
"""Genetic Algorithm router — evolve routing on 192 cores."""
import json,time,os,subprocess,sys,random
from multiprocessing import Pool,cpu_count

os.chdir('/root/analog-trial/layout')
with open('netlist.json') as f: netlist=json.load(f)
with open('placement.json') as f: placement=json.load(f)
with open('output/routing.json') as f: routing=json.load(f)
with open('atk/data/device_lib.json') as f: dl=json.load(f)
with open('atk/data/device_lib_magic.json') as f: dlm=json.load(f)
instances=placement['instances']
aps=routing['access_points']
SCALE=10
def nm(v):return int(round(v/SCALE))
def gp(dev):
    dt=dev['type'];lib=dl.get(dt,{});c=lib.get('class','')
    return c in('nmos','pmos','resistor')or any(k in dt for k in('nmos','pmos','rhigh','cap','cmim'))

# Base device lines (constant)
base=[]
for dev in netlist['devices']:
    if not gp(dev):continue
    name=dev['name'];cell=f'dev_{name}'.lower().replace('.','_')
    inst=instances.get(name,{})
    x=int(round(inst.get('x_um',0)*100));y=int(round(inst.get('y_um',0)*100))
    base.extend([f'use {cell} {cell}_0',f'transform 1 0 {x} 0 1 {y}',f'box 0 0 1 1'])

# Precompute filter data
net_devs={}
for net in netlist['nets']:
    devs=set()
    for pin in net['pins']:devs.add(pin.split('.')[0])
    net_devs[net['name']]=devs
dev_bboxes={}
for name,inst in instances.items():
    mi=dlm.get(inst.get('type',''))
    if mi and 'bbox' in mi:
        bb=mi['bbox'];ox=inst.get('x_um',0)*1000;oy=inst.get('y_um',0)*1000
        dev_bboxes[name]=(int(round(ox+bb[0])),int(round(oy+bb[1])),int(round(ox+bb[2])),int(round(oy+bb[3])))

LN={0:'metal1',1:'metal2',2:'metal3',3:'metal4',-1:'via1',-2:'via2',-3:'via3'}

# Classify ALL segments: passed vs filtered
all_segs=[]  # (net, seg, passed_filter)
for nn,route in routing.get('signal_routes',{}).items():
    allowed=net_devs.get(nn,set())
    for seg in route.get('segments',[]):
        if len(seg)<5:continue
        x1,y1,x2,y2,lyr=seg[:5];ln=LN.get(lyr)
        if not ln:continue
        hw=125 if lyr==1 else(100 if lyr<0 else 150)
        if lyr>=0:
            if x1==x2:sb=(x1-hw,min(y1,y2),x1+hw,max(y1,y2))
            else:sb=(min(x1,x2),y1-hw,max(x1,x2),y1+hw)
        else:sb=(x1-hw,y1-hw,x1+hw,y1+hw)
        skip=False
        for dn,db in dev_bboxes.items():
            if dn in allowed:continue
            if sb[2]>db[0] and sb[0]<db[2] and sb[3]>db[1] and sb[1]<db[3]:skip=True;break
        all_segs.append((nn,seg,ln,hw,not skip))

passed=[i for i,s in enumerate(all_segs) if s[4]]
filtered=[i for i,s in enumerate(all_segs) if not s[4]]
print(f"Segments: {len(all_segs)} total, {len(passed)} passed, {len(filtered)} filtered",flush=True)

# Power lines (constant)
pwr_lines=[]
for rn,rail in routing.get('power',{}).get('rails',{}).items():
    y=rail['y'];x1,x2=rail['x1'],rail['x2'];hw=rail['width']//2
    pwr_lines.append('<< metal3 >>');pwr_lines.append(f'rect {nm(min(x1,x2))} {nm(y-hw)} {nm(max(x1,x2))} {nm(y+hw)}')
for drop in routing.get('power',{}).get('drops',[]):
    vbar=drop.get('m3_vbar')
    if vbar:
        vx1,vy1,vx2,vy2=vbar;vhw=100;pwr_lines.append('<< metal3 >>')
        if vx1==vx2:pwr_lines.append(f'rect {nm(vx1-vhw)} {nm(min(vy1,vy2))} {nm(vx1+vhw)} {nm(max(vy1,vy2))}')
        else:pwr_lines.append(f'rect {nm(min(vx1,vx2))} {nm(vy1-vhw)} {nm(max(vx1,vx2))} {nm(vy1+vhw)}')

# AP lines (constant)
m2p=440;v1=100;m1p=185;m1s=40
ap_lines=[]
for pk,ap in aps.items():
    px,py=ap['x'],ap['y'];vp=ap.get('via_pad',{})
    if vp:
        ap_lines.append('<< via1 >>');ap_lines.append(f'rect {nm(px-v1)} {nm(py-v1)} {nm(px+v1)} {nm(py+v1)}')
        ap_lines.append('<< metal1 >>');ap_lines.append(f'rect {nm(px-m1p)} {nm(py-m1p)} {nm(px+m1p)} {nm(py+m1p)}')
        ap_lines.append('<< metal2 >>');ap_lines.append(f'rect {nm(px-m2p)} {nm(py-m2p)} {nm(px+m2p)} {nm(py+m2p)}')
    stub=ap.get('m1_stub')
    if stub:
        cx=(stub[0]+stub[2])//2
        ap_lines.append('<< metal1 >>');ap_lines.append(f'rect {nm(cx-m1s)} {nm(stub[1])} {nm(cx+m1s)} {nm(stub[3])}')

def evaluate(genome):
    """genome = set of segment indices to INCLUDE."""
    idx,seg_set=genome
    W=f"/tmp/ga_{idx}"
    try:
        os.makedirs(W,exist_ok=True)
        mag=['magic','tech ihp-sg13g2',f'timestamp {int(time.time())}']+base
        cl=None
        for si in seg_set:
            nn,seg,ln,hw,_=all_segs[si]
            x1,y1,x2,y2,lyr=seg[:5]
            if ln!=cl:mag.append(f'<< {ln} >>');cl=ln
            if lyr>=0:
                if x1==x2:mag.append(f'rect {nm(x1-hw)} {nm(min(y1,y2))} {nm(x1+hw)} {nm(max(y1,y2))}')
                else:mag.append(f'rect {nm(min(x1,x2))} {nm(y1-hw)} {nm(max(x1,x2))} {nm(y1+hw)}')
            else:mag.append(f'rect {nm(x1-hw)} {nm(y1-hw)} {nm(x1+hw)} {nm(y1+hw)}')
        mag.extend(pwr_lines)
        mag.extend(ap_lines)
        mag.append('<< end >>')
        with open(f'{W}/soilz.mag','w') as f:f.write('\n'.join(mag)+'\n')
        os.system(f'cp /tmp/magic_soilz/dev_*.mag {W}/')
        os.system(f'cp /tmp/magic_soilz/phase_c_fast.tcl {W}/')
        os.system(f'cd {W} && CAD_ROOT=/usr/local/lib magic -noconsole -dnull -T /root/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/magic/ihp-sg13g2 < phase_c_fast.tcl > /dev/null 2>&1')
        with open(f'{W}/soilz_flat.spice') as f:lines=f.readlines()
        out=[]
        for line in lines:
            if line.startswith('X'):
                parts=line.split()
                if 'sg13_lv_nmos' in parts or 'sg13_lv_pmos' in parts:
                    model='sg13_lv_nmos' if 'sg13_lv_nmos' in parts else 'sg13_lv_pmos'
                    s,g,d,b=parts[1],parts[2],parts[3],parts[4]
                    w=l=''
                    for p in parts:
                        if p.startswith('w='):w=p.split('=')[1]
                        elif p.startswith('l='):l=p.split('=')[1]
                    if w.startswith('70n') and l.startswith('70n'):continue
                    out.append(f'M{parts[0][1:]} {d} {g} {s} {b} {model} W={w} L={l}\n')
                elif 'rhigh' in parts:
                    w=l=''
                    for p in parts:
                        if p.startswith('w='):w=p.split('=')[1]
                        elif p.startswith('l='):l=p.split('=')[1]
                    out.append(f'R{parts[0][1:]} {parts[1]} {parts[2]} rhigh W={w} L={l}\n')
                elif 'cap_cmim' in parts:
                    w=l=''
                    for p in parts:
                        if p.startswith('w='):w=p.split('=')[1]
                        elif p.startswith('l='):l=p.split('=')[1]
                    out.append(f'C{parts[0][1:]} {parts[1]} {parts[2]} cap_cmim W={w} L={l}\n')
                else:out.append(line)
            else:out.append(line)
        with open(f'{W}/soilz_clean.spice','w') as f:f.writelines(out)
        with open(f'{W}/ng.tcl','w') as f:
            f.write(f'source /usr/local/lib/netgen/tcl/netgen.tcl\nset s /root/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/netgen/ihp-sg13g2_setup.tcl\nlvs {{{W}/soilz_clean.spice soilz_flat}} {{soilz_lvs.spice soilz}} $s {W}/comp.out\nquit\n')
        subprocess.run(f'/usr/local/lib/netgen/tcl/netgenexec < {W}/ng.tcl',shell=True,capture_output=True,text=True,timeout=60,cwd='/root/analog-trial/layout')
        devs=0
        with open(f'{W}/comp.out') as cf:
            for line in cf:
                if 'Number of devices' in line and 'Mismatch' in line:
                    try:devs=int(line.split(':')[1].strip().split()[0])
                    except:pass
                    break
        os.system(f'rm -rf {W}')
        return devs
    except:
        os.system(f'rm -rf {W}')
        return 0

# GA
NCORES=cpu_count()
POP_SIZE=NCORES  # 192
GENERATIONS=200
MUTATION_RATE=0.08  # flip 5% of filtered segments

# Initial population: baseline + random variations
baseline_set=set(passed)
population=[]
# First individual: baseline (all passed, no filtered)
population.append(set(passed))
# Rest: randomly include some filtered segments
for _ in range(POP_SIZE-1):
    genome=set(passed)
    for fi in filtered:
        if random.random()<0.15:  # 15% chance to include each filtered seg
            genome.add(fi)
    # Also randomly remove some passed segments
    for pi in passed:
        if random.random()<0.03:  # 3% chance to exclude
            genome.discard(pi)
    population.append(genome)

print(f"GA: pop={POP_SIZE}, gen={GENERATIONS}, segs={len(all_segs)}, filtered={len(filtered)}",flush=True)

best_ever=0
best_genome=None
for gen in range(GENERATIONS):
    t0=time.time()
    # Evaluate all
    work=[(i,pop) for i,pop in enumerate(population)]
    with Pool(NCORES) as pool:
        scores=pool.map(evaluate,work)
    
    # Sort by fitness
    scored=list(zip(scores,population))
    scored.sort(key=lambda x:-x[0])
    
    gen_best=scored[0][0]
    gen_median=scored[len(scored)//2][0]
    
    if gen_best>best_ever:
        best_ever=gen_best
        best_genome=scored[0][1]
    
    elapsed=time.time()-t0
    print(f"Gen {gen+1}/{GENERATIONS}: best={gen_best} median={gen_median} alltime={best_ever} ({elapsed:.1f}s)",flush=True)
    
    if gen_best>=255:
        print("PERFECT MATCH!",flush=True)
        break
    
    # Selection: keep top 50%
    survivors=[g for _,g in scored[:POP_SIZE//2]]
    
    # Breed: crossover + mutation
    children=[]
    while len(children)<POP_SIZE//2:
        p1,p2=random.sample(survivors,2)
        # Crossover: take union and randomly thin
        child=set()
        for si in p1|p2:
            if si in p1 and si in p2:
                child.add(si)  # both parents have it
            elif random.random()<0.5:
                child.add(si)  # one parent has it
        # Mutation
        for fi in filtered:
            if random.random()<MUTATION_RATE:
                if fi in child:child.discard(fi)
                else:child.add(fi)
        for pi in passed:
            if random.random()<MUTATION_RATE*0.3:
                if pi in child:child.discard(pi)
                else:child.add(pi)
        children.append(child)
    
    population=survivors+children

print(f"\n=== GA COMPLETE ===",flush=True)
print(f"Best ever: {best_ever}",flush=True)
if best_genome:
    extra=best_genome-set(passed)
    missing=set(passed)-best_genome
    print(f"Extra segments (from filtered): {len(extra)}",flush=True)
    print(f"Removed segments (from passed): {len(missing)}",flush=True)
    with open('/tmp/ga_best_genome.json','w') as f:
        json.dump({'score':best_ever,'extra':list(extra),'missing':list(missing)},f)
