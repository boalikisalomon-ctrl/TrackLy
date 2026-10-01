from zk import ZK

IP = '192.168.1.201'
PORT = 4370

zk = ZK(IP, port=PORT, timeout=5, password=1324, force_udp=False, ommit_ping=False)
conn = None

try:
    print(f"Connexion à {IP}:{PORT}...")
    conn = zk.connect()
    print("CONNECTÉ À LA POINTEUSE")

    users = conn.get_users()
    print(f"--- {len(users)} employés enregistrés ---")
    for u in users:
        print(f"ID : {u.user_id} | Nom: {u.name}")

    print("\n--- 10 derniers pointages ---")
    atts = conn.get_attendance()
    if not atts:
        print("Aucun pointage pour l'instant. Mets ton doigt sur la pointeuse et relance.")
    else:
        for a in atts[-10:]:
            print(f"Employé {a.user_id} a pointé le {a.timestamp}")

except Exception as e:
    print(f"ERREUR : {e}")
    print("\nVérifie :")
    print("1. Pointeuse branchée en câble réseau à la box ?")
    print("2. Ton PC est sur le même réseau que la box ?")
    print("3. Fais un ping : ping 192.168.1.201")
finally:
    if conn:
        conn.disconnect()
        print("\nConnexion fermée.")