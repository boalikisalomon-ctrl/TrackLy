from zk import ZK
import sqlite3

IP = "192.168.1.201"
PORT = 4370

# Mapping du code "punch" de pyzk vers un type lisible
TYPES_POINTAGE = {
    0: "Arrivée",
    1: "Départ",
}

conn_db = sqlite3.connect("gestion_absences.db")
cur = conn_db.cursor()

zk = ZK(IP, port=PORT, timeout=5, password=1324)
conn_pointeuse = None

try:
    print("Connexion à la pointeuse...")
    conn_pointeuse = zk.connect()
    print("Connecté.")

    # 1. Synchroniser les employés
    from auth import creer_ou_mettre_a_jour_compte_employe
    users = conn_pointeuse.get_users()
    for u in users:
        # INSERT OR IGNORE : n'écrase pas un employé déjà existant
        # (donc ne touche pas au champ "actif" s'il a été désactivé)
        cur.execute("""
            INSERT OR IGNORE INTO employes (id, nom, service, actif)
            VALUES (?, ?, NULL, 1)
        """, (u.user_id, u.name))
        try:
            creer_ou_mettre_a_jour_compte_employe(u.user_id, u.name)
        except Exception:
            pass
    print(f"{len(users)} employés synchronisés.")

    # 2. Synchroniser les pointages
    attendances = conn_pointeuse.get_attendance()
    nb_nouveaux = 0
    for a in attendances:
        type_pointage = TYPES_POINTAGE.get(a.punch, "inconnu")

        # On vérifie si ce pointage exact existe déjà, pour éviter les doublons
        cur.execute("""
            SELECT id FROM pointages
            WHERE employe_id = ? AND date_heure = ?
        """, (a.user_id, str(a.timestamp)))
        existe_deja = cur.fetchone()

        if not existe_deja:
            cur.execute("""
                INSERT INTO pointages (employe_id, date_heure, type)
                VALUES (?, ?, ?)
            """, (a.user_id, str(a.timestamp), type_pointage))
            nb_nouveaux += 1

    print(f"{nb_nouveaux} nouveaux pointages ajoutés.")

    conn_db.commit()
    print("Synchronisation terminée avec succès.")

except Exception as e:
    print(f"ERREUR : {e}")

finally:
    if conn_pointeuse:
        conn_pointeuse.disconnect()
    conn_db.close()