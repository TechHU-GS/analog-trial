---
name: ecs-magic
description: Create Aliyun ECS spot instance for Magic VLSI routing and LVS. Compile Magic+Netgen, sync project, run parallel routing exploration.
user_invocable: true
arguments: |
  Subcommands:
    (no args)     — Full cycle: create instance → setup → rsync → run router
    check         — Check progress of running router
    release       — Release (terminate) the instance
    status        — Show instance status
    image         — Create custom image (preserves Magic+Netgen+PDK env)
    shell         — Print SSH command to connect
    rsync         — Sync project files to instance
    run <script>  — Run a specific script on the instance
---

# ECS Magic Skill

Spin up an Aliyun ECS spot instance for Magic VLSI IC layout routing and LVS verification.

## Infrastructure (Reuse from gem-verify)

| Resource | ID | Notes |
|----------|-----|-------|
| VPC | vpc-bp11x4a2e40h86vr3hw8e | gem-verify |
| VSwitch | vsw-bp17mn8ivkpxno8wfatrz | cn-hangzhou-j |
| Security Group | sg-bp1a7pk4m1umj1nejjs4 | SSH 22 open |
| Key Pair | gem-verify | Private: `~/.ssh/gem-verify.pem` |
| SSH shorthand | `ssh -i ~/.ssh/gem-verify.pem root@<IP>` | |

## Instance Specs

| 场景 | 实例类型 | 规格 | 竞价价格 | 用途 |
|------|---------|------|---------|------|
| **推荐** | ecs.c8a.16xlarge | 64C/128G AMD EPYC | ~1.5 CNY/h | 64 并行 Magic extraction |
| 轻量 | ecs.c7.4xlarge | 16C/32G | ~0.6 CNY/h | 16 并行，日常验证 |
| 备选 | ecs.c8a.8xlarge | 32C/64G | ~0.8 CNY/h | 32 并行 |

Magic 每进程 ~100MB RAM。64 并行 = 6.4GB。CPU 是瓶颈，不是内存。

## Execution Steps

### Subcommand: (default) — Full cycle

#### Step 1: Check for custom image

```bash
aliyun ecs DescribeImages --RegionId cn-hangzhou --ImageOwnerAlias self \
  --ImageName ic-magic --Status Available 2>&1
```

- If `ic-magic-*` image exists → use it (skip Step 3 setup)
- If no image → use base: `ubuntu_22_04_x64_20G_alibase_20260213.vhd`

#### Step 2: Create spot instance

```bash
aliyun ecs RunInstances \
  --RegionId cn-hangzhou \
  --InstanceType ecs.c8a.16xlarge \
  --ImageId <IMAGE_ID> \
  --SecurityGroupId sg-bp1a7pk4m1umj1nejjs4 \
  --VSwitchId vsw-bp17mn8ivkpxno8wfatrz \
  --InstanceName ic-magic-$(date +%m%d) \
  --InternetMaxBandwidthOut 10 \
  --InternetChargeType PayByTraffic \
  --KeyPairName gem-verify \
  --SystemDisk.Category cloud_essd \
  --SystemDisk.Size 40 \
  --InstanceChargeType PostPaid \
  --SpotStrategy SpotAsPriceGo \
  --Amount 1
```

Wait 15-20s, get IP:
```bash
aliyun ecs DescribeInstances --RegionId cn-hangzhou \
  --InstanceName ic-magic-* --Status Running
```

#### Step 3: Setup environment (SKIP if using custom image)

SSH into instance and run:

```bash
#!/bin/bash
set -e

# System packages
apt-get update && apt-get install -y \
  build-essential tcl8.6-dev tk8.6-dev libx11-dev \
  python3 python3-pip git m4 csh

# Magic VLSI
cd /opt
git clone https://github.com/RTimothyEdwards/magic.git
cd magic
./configure --prefix=/usr/local
make -j$(nproc) && make install
echo "Magic: $(magic --version 2>&1 | head -1)"

# Netgen LVS
cd /opt
git clone https://github.com/RTimothyEdwards/netgen.git
cd netgen
./configure --prefix=/usr/local \
  --with-tcl=/usr/lib/tcl8.6 --with-tk=/usr/lib/tk8.6
make -j$(nproc) && make install
echo "Netgen installed"

# IHP PDK
cd /root
git clone --depth 1 https://github.com/IHP-GmbH/IHP-Open-PDK.git pdk/IHP-Open-PDK
echo "IHP PDK cloned"

# Create convenience symlinks
mkdir -p /root/.local/bin /root/.local/lib
ln -sf /usr/local/bin/magic /root/.local/bin/magic
ln -sf /usr/local/lib/netgen /root/.local/lib/netgen

echo "=== Setup complete ==="
magic --version 2>&1 | head -1
```

#### Step 4: Rsync project

```bash
rsync -az --exclude='output/*.gds' --exclude='__pycache__/' \
  -e "ssh -i ~/.ssh/gem-verify.pem -o StrictHostKeyChecking=no" \
  /Users/techhu/Code/GS_IC/designs/analog-trial/ \
  root@<IP>:/root/analog-trial/
```

Also sync the /tmp/magic_soilz device subcells if they exist:
```bash
rsync -az -e "ssh -i ~/.ssh/gem-verify.pem" \
  /tmp/magic_soilz/ root@<IP>:/tmp/magic_soilz/
```

#### Step 5: Run Magic-in-the-loop router

Transfer and start:
```bash
ssh -i ~/.ssh/gem-verify.pem root@<IP> \
  'cd /root/analog-trial/layout && \
   nohup python3 -m atk.magic_in_loop_router > /tmp/router.log 2>&1 &'
```

Or run a custom script:
```bash
scp -i ~/.ssh/gem-verify.pem <local_script> root@<IP>:/tmp/run.sh
ssh -i ~/.ssh/gem-verify.pem root@<IP> 'chmod +x /tmp/run.sh && nohup /tmp/run.sh > /tmp/run.log 2>&1 &'
```

#### Step 6: Output monitoring info

```
====== ECS Magic 已启动 ======
实例: <INSTANCE_ID> (<IP>)
规格: ecs.c8a.16xlarge (64C/128G)

监控:
  ssh -i ~/.ssh/gem-verify.pem root@<IP>
  tail -f /tmp/router.log
  # 检查 Magic 进程数:
  pgrep -c magic

环境:
  Magic: /usr/local/bin/magic
  Netgen: /usr/local/lib/netgen/tcl/netgenexec
  PDK: /root/pdk/IHP-Open-PDK
  项目: /root/analog-trial/layout

预估: 64 并行 Magic-in-the-loop ~30-60 min
========================================
```

---

### Subcommand: check

```bash
ssh -i ~/.ssh/gem-verify.pem root@<IP> \
  'echo "Magic procs: $(pgrep -c magic 2>/dev/null || echo 0)"; \
   echo "CPU: $(uptime | sed "s/.*load average: //")"; \
   free -h | grep Mem; \
   tail -5 /tmp/router.log 2>/dev/null || echo "No log yet"'
```

### Subcommand: shell

```
ssh -i ~/.ssh/gem-verify.pem root@<IP>
```

### Subcommand: rsync

```bash
rsync -az --exclude='output/*.gds' --exclude='__pycache__/' \
  -e "ssh -i ~/.ssh/gem-verify.pem -o StrictHostKeyChecking=no" \
  /Users/techhu/Code/GS_IC/designs/analog-trial/ \
  root@<IP>:/root/analog-trial/
```

### Subcommand: release

```bash
# Always ask: need to save image first?
aliyun ecs DeleteInstance --InstanceId <INSTANCE_ID> --Force true
```

### Subcommand: image

```bash
aliyun ecs CreateImage --RegionId cn-hangzhou \
  --InstanceId <INSTANCE_ID> \
  --ImageName ic-magic-$(date +%Y%m%d) \
  --Description "Magic+Netgen+IHP PDK for analog IC routing"
```

### Subcommand: status

```bash
aliyun ecs DescribeInstances --RegionId cn-hangzhou \
  --InstanceName ic-magic-* 2>&1
```

---

## Magic Pipeline Commands (on server)

### Full extraction + LVS
```bash
cd /root/analog-trial/layout
export CAD_ROOT=/usr/local/lib
MAGIC="magic -noconsole -dnull -T /root/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/magic/ihp-sg13g2"

# Phase A: generate device subcells
$MAGIC < /tmp/magic_soilz/phase_a.tcl

# Strip PCell M2
python3 -m atk.strip_pcell_m2 /tmp/magic_soilz

# Phase C: flatten + extract
$MAGIC < /tmp/magic_soilz/phase_c_fast.tcl

# Convert SPICE
python3 -c "
from atk.gen_magic_layout import convert_spice_for_netgen
convert_spice_for_netgen('/tmp/magic_soilz/soilz_flat.spice', '/tmp/magic_soilz/soilz_netgen.spice')
"

# Netgen LVS
echo "source /usr/local/lib/netgen/tcl/netgen.tcl
set setup /root/pdk/IHP-Open-PDK/ihp-sg13g2/libs.tech/netgen/ihp-sg13g2_setup.tcl
lvs {/tmp/magic_soilz/soilz_netgen.spice soilz_flat} {soilz_lvs.spice soilz} \$setup /tmp/magic_soilz/comp.out
quit" | /usr/local/lib/netgen/tcl/netgenexec
```

### Parallel routing exploration (64 cores)
```bash
# Run N routing variants in parallel
for i in $(seq 1 64); do
  (
    WORK=/tmp/magic_route_$i
    mkdir -p $WORK
    cp -r /tmp/magic_soilz/dev_*.mag $WORK/
    # Generate variant routing...
    # Extract + LVS...
    echo "Variant $i: done" >> /tmp/parallel.log
  ) &
done
wait
echo "All variants complete"
```

## Known Issues

- **Magic on macOS**: ext2spice sometimes hangs on complex layouts. Linux is stable.
- **PDK path**: Server uses `/root/pdk/IHP-Open-PDK`, local uses `~/pdk/IHP-Open-PDK`. Scripts that hardcode `$HOME` paths need adjustment.
- **Netgen path**: Server `/usr/local/lib/netgen/tcl/netgenexec`, local `~/.local/lib/netgen/tcl/netgenexec`.
- **No X11 needed**: Magic runs with `-dnull` (no display). Server doesn't need desktop.

## Image Management

- Naming: `ic-magic-YYYYMMDD`
- Cost: ~0.7 CNY/month for 40G disk
- Image includes: Magic, Netgen, IHP PDK, Python3, build tools
- Image does NOT include: project code (always rsync), /tmp/magic_soilz (regenerated)
