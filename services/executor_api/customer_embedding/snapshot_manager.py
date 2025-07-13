import os
import json
import shutil
from datetime import datetime
from pathlib import Path
import tarfile
import tempfile

# 🔧 Ayarlar
SNAPSHOT_INTERVAL = 3  # Her 300 çağrıda bir
MAX_SNAPSHOTS = 5

# Ortam değişkenlerinden alınan yollar
QDRANT_COLLECTION_DIR = "/qdrant_storage"
SNAPSHOT_BACKUP_DIR   = "/snapshots"
SNAPSHOT_STATE_FILE = Path(SNAPSHOT_BACKUP_DIR) / "snapshot_state_customer.json"


def get_total_customer_count(mongo_db):
    """Semantic embedding oluşturulmuş çağrı sayısını verir"""
    return mongo_db["customer_profiles_rag"].count_documents({"embedding_created_at": {"$exists": True}})




def get_last_snapshot_count() -> int:
    if not SNAPSHOT_STATE_FILE.exists():
        print("📂 snapshot_state.json bulunamadı, sıfırdan başlatılıyor.")
        set_last_snapshot_count(0)  # ← Bu satır eklendi!
        return 0
    try:
        with open(SNAPSHOT_STATE_FILE) as f:
            data = json.load(f)
            return data.get("last_snapshot_total", 0)
    except Exception as e:
        print(f"⚠️ snapshot_state.json okunamadı: {e}")
        return 0


def set_last_snapshot_count(count: int):
    """Son snapshot alınan call sayısını günceller"""
    try:
        os.makedirs(SNAPSHOT_BACKUP_DIR, exist_ok=True)
        with open(SNAPSHOT_STATE_FILE, "w") as f:
            json.dump({"last_snapshot_total": count}, f)
    except Exception as e:
        print(f"❌ Snapshot state kaydedilemedi: {e}")



def save_snapshot_if_needed(current_total: int):
    last_snapshot = get_last_snapshot_count()

    print(f"📊 Snapshot kontrol: current_total={current_total}, last_snapshot={last_snapshot}")

    if current_total - last_snapshot < SNAPSHOT_INTERVAL:
        print("⏭️ Snapshot zamanı değil, geçiliyor.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"snapshot_{timestamp}.tar.gz"
    archive_path = Path(SNAPSHOT_BACKUP_DIR) / archive_name

    if not Path(QDRANT_COLLECTION_DIR).exists():
        print(f"❌ Koleksiyon dizini bulunamadı: {QDRANT_COLLECTION_DIR}")
        return

    # 1️⃣ Geçici klasöre Qdrant verilerini kopyala
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "qdrant_data"
        shutil.copytree(QDRANT_COLLECTION_DIR, tmp_path)

        # 2️⃣ .tar.gz arşiv oluştur
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(tmp_path, arcname="qdrant_data")

    print(f"✅ Snapshot alındı ve arşivlendi: {archive_path}")

    # 3️⃣ State güncelle + temizlik
    set_last_snapshot_count(current_total)
    cleanup_old_snapshots()

def cleanup_old_snapshots():
    """En fazla MAX_SNAPSHOTS adet .tar.gz snapshot tutar, eskileri siler"""
    snapshots = sorted(
        Path(SNAPSHOT_BACKUP_DIR).glob("snapshot_*.tar.gz"),
        key=lambda p: p.stat().st_mtime
    )

    if len(snapshots) <= MAX_SNAPSHOTS:
        return

    for snapshot_file in snapshots[:-MAX_SNAPSHOTS]:
        snapshot_file.unlink()
        print(f"🗑️ Eski snapshot silindi: {snapshot_file}")