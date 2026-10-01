import sqlite3

HEURE_LIMITE = "08:00:00"  # heure officielle d'arrivée

conn = sqlite3.connect("gestion_absences.db")
cur = conn.cursor()

# Récupérer tous les pointages, triés par employé puis par date/heure
cur.execute("""
    SELECT employe_id, date_heure, type
    FROM pointages
    ORDER BY employe_id, date_heure
""")
pointages = cur.fetchall()

# Regrouper les pointages par (employé, jour)
jours = {}

for employe_id, date_heure, type_pointage in pointages:
    date_str, heure_str = date_heure.split(" ")
    cle = (employe_id, date_str)

    if cle not in jours:
        jours[cle] = {"arrivee": None, "depart": None}

    if type_pointage == "arrivée":
        if jours[cle]["arrivee"] is None or heure_str < jours[cle]["arrivee"]:
            jours[cle]["arrivee"] = heure_str
    elif type_pointage == "départ":
        if jours[cle]["depart"] is None or heure_str > jours[cle]["depart"]:
            jours[cle]["depart"] = heure_str

# Calculer le statut et insérer dans la table presences
nb_ajoutes = 0
for (employe_id, date_str), horaires in jours.items():
    heure_arrivee = horaires["arrivee"]
    heure_depart = horaires["depart"]

    if heure_arrivee and heure_arrivee > HEURE_LIMITE:
        statut = "en retard"
    elif heure_arrivee:
        statut = "présent"
    else:
        statut = "absent"

    cur.execute("""
        SELECT id FROM presences WHERE employe_id = ? AND date = ?
    """, (employe_id, date_str))
    existe = cur.fetchone()

    if not existe:
        cur.execute("""
            INSERT INTO presences (employe_id, date, heure_arrivee, heure_depart, statut)
            VALUES (?, ?, ?, ?, ?)
        """, (employe_id, date_str, heure_arrivee, heure_depart, statut))
        nb_ajoutes += 1

conn.commit()
conn.close()

print(f"{nb_ajoutes} journées de présence générées.")