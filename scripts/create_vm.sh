#!/usr/bin/env bash
# ============================================================
#  create_vm.sh — สร้าง Windows VM (mt5-vm) บน GCP จาก Cloud Shell
#  รันจาก root ของ repo:  bash scripts/create_vm.sh <github_token> [your_ip/32]
#    - github_token : (optional) PAT ไว้ให้ VM clone repo ตอนบูต
#    - your_ip/32   : (optional) จำกัด RDP เฉพาะ IP คุณ (default เปิดทุก IP)
#  ทำให้: enable compute API + create VM (ติด startup script) + firewall RDP
#         + reset Windows password + list
# ============================================================
set -e

GH_TOKEN="${1:-}"
RDP_SRC="${2:-}"
ZONE="asia-southeast1-b"

# ── ความปลอดภัย: ไม่เปิด RDP ทั้งอินเทอร์เน็ตโดยไม่ตั้งใจ ──────────────
# RDP (3389) ที่เปิดให้ 0.0.0.0/0 = เป้า brute-force/hack อันดับต้นๆ ของ Windows VM
if [ -z "$RDP_SRC" ]; then
  echo ""
  echo "  ⚠️  ไม่ได้ระบุ IP สำหรับจำกัด RDP (arg ที่ 2)"
  echo "     การเปิด RDP (3389) ให้ทั้งอินเทอร์เน็ต (0.0.0.0/0) เสี่ยงโดน hack สูงมาก"
  echo "     เช็ก IP บ้าน/มือถือคุณที่ whatismyip.com (อย่าใช้ IP ของ Cloud Shell)"
  echo ""
  read -r -p "  พิมพ์ IP ที่จะอนุญาต เช่น 1.2.3.4/32 (Enter = เปิดทั้งอินเทอร์เน็ต ไม่แนะนำ): " ANS
  if [ -n "$ANS" ]; then
    RDP_SRC="$ANS"
  else
    read -r -p "  ยืนยันเปิด RDP ทั้งอินเทอร์เน็ต? พิมพ์ 'yes' เท่านั้นจึงจะดำเนินการ: " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
      echo "  ยกเลิก — รันใหม่พร้อมระบุ IP:  bash scripts/create_vm.sh \"$GH_TOKEN\" <your_ip>/32"
      exit 1
    fi
    RDP_SRC="0.0.0.0/0"
  fi
fi
echo "    RDP source range = $RDP_SRC"

echo "==> [1/5] Ensuring Compute Engine API ..."
gcloud services enable compute.googleapis.com

META_TOKEN=()
if [ -n "$GH_TOKEN" ]; then
  META_TOKEN=(--metadata "gh-token=$GH_TOKEN")
else
  echo "    !! ไม่ได้ใส่ GitHub token — VM จะลง Python/Git/MT5 ให้ แต่ 'ไม่ clone repo'"
  echo "       (clone เองทีหลังตอน RDP ก็ได้)"
fi

echo "==> [2/5] Creating mt5-vm (e2-medium / Windows Server 2022 / Singapore) ..."
gcloud compute instances create mt5-vm \
  --zone="$ZONE" \
  --machine-type=e2-medium \
  --image-family=windows-2022 --image-project=windows-cloud \
  --boot-disk-size=50GB --boot-disk-type=pd-balanced \
  "${META_TOKEN[@]}" \
  --metadata-from-file windows-startup-script-ps1=scripts/setup_vm_startup.ps1

echo "==> [3/5] RDP firewall rule (source: $RDP_SRC) ..."
# create ถ้ายังไม่มี — ถ้ามีอยู่แล้วให้ update source-ranges ตาม IP ที่เลือกรอบนี้
# (กันกรณี rule เก่าเปิด 0.0.0.0/0 ค้างไว้จากการรันครั้งก่อน)
gcloud compute firewall-rules create allow-rdp \
  --allow=tcp:3389 --source-ranges="$RDP_SRC" 2>/dev/null \
  || gcloud compute firewall-rules update allow-rdp --source-ranges="$RDP_SRC"

echo "==> [4/5] ตั้งรหัส Windows (user: trader) — *** เก็บรหัสที่ขึ้นไว้ ***"
gcloud compute reset-windows-password mt5-vm --zone="$ZONE" --user=trader --quiet

echo "==> [5/5] VM list (ดู EXTERNAL_IP สำหรับ RDP) :"
gcloud compute instances list

echo ""
echo "DONE. รอ ~5 นาที ให้ startup script ติดตั้งเสร็จ แล้ว RDP เข้า EXTERNAL_IP"
echo "  user=trader  password=ที่ขึ้นด้านบน"
