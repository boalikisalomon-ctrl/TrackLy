import sqlite3

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
    parts = date_heure.split(" ")
    if len(parts) < 2:
        continue
    date_str, heure_str = parts[0], parts[1]
    cle = (employe_id, date_str)

    if cle not in jours:
        jours[cle] = {"arrivee": None, "depart": None}

    type_str = str(type_pointage).lower() if type_pointage else ""
    if "arriv" in type_str or type_str in ("0", 0):
        if jours[cle]["arrivee"] is None or heure_str < jours[cle]["arrivee"]:
            jours[cle]["arrivee"] = heure_str
    elif "d" in type_str or "depart" in type_str or type_str in ("1", 1):
        if jours[cle]["depart"] is None or heure_str > jours[cle]["depart"]:
            jours[cle]["depart"] = heure_str
    else:
        if jours[cle]["arrivee"] is None or heure_str < jours[cle]["arrivee"]:
            jours[cle]["arrivee"] = heure_str
        if jours[cle]["depart"] is None or heure_str > jours[cle]["depart"]:
            jours[cle]["depart"] = heure_str

# Calculer le statut selon l'horaire propre à chaque employé (cours de jour / soir)
nb_ajoutes = 0
for (employe_id, date_str), horaires in jours.items():
    heure_arrivee = horaires["arrivee"]
    heure_depart = horaires["depart"]

    cur.execute("""
        SELECT COALESCE(h.heure_debut, e.heure_debut_prevue, '08:00')
        FROM employes e
        LEFT JOIN horaires_employes h ON e.id = h.employe_id
        WHERE e.id = ?
    """, (employe_id,))
    row = cur.fetchone()
    heure_debut = row[0] if row else "08:00"
    limite = f"{heure_debut}:00" if len(heure_debut) == 5 else heure_debut

    if heure_arrivee and heure_arrivee > limite:
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
    else:
        cur.execute("""
            UPDATE presences
            SET heure_arrivee = ?, heure_depart = ?, statut = ?
            WHERE id = ?
        """, (heure_arrivee, heure_depart, statut, existe[0]))

conn.commit()
conn.close()

print(f"{nb_ajoutes} journées de présence traitées avec les horaires personnalisés.")
