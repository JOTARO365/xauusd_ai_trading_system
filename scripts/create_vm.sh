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
RDP_SRC="${2:-0.0.0.0/0}"
ZONE="asia-southeast1-b"

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
gcloud compute firewall-rules create allow-rdp \
  --allow=tcp:3389 --source-ranges="$RDP_SRC" 2>/dev/null \
  || echo "    (firewall rule อาจมีอยู่แล้ว — ข้าม)"

echo "==> [4/5] ตั้งรหัส Windows (user: trader) — *** เก็บรหัสที่ขึ้นไว้ ***"
gcloud compute reset-windows-password mt5-vm --zone="$ZONE" --user=trader --quiet

echo "==> [5/5] VM list (ดู EXTERNAL_IP สำหรับ RDP) :"
gcloud compute instances list

echo ""
echo "DONE. รอ ~5 นาที ให้ startup script ติดตั้งเสร็จ แล้ว RDP เข้า EXTERNAL_IP"
echo "  user=trader  password=ที่ขึ้นด้านบน"
