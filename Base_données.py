import sqlite3
#Connexion (crée le fichier gestion_absences.db)
conn = sqlite3.connect ("gestion_absences.db")
cur = conn.cursor()

#Table des employés
cur.execute("""
CREATE TABLE IF NOT EXISTS employes (
  id INTEGER PRIMARY KEY,
  nom TEXT NOT NULL,
  service TEXT,
  actif INTEGER DEFAULT 1
)
""")

#Table des pointages bruts (chaque passage sur le pointage)
cur.execute ("""
      CREATE TABLE IF NOT EXISTS pointages(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      employe_id INTEGER NOT NULL,
      date_heure TEXT NOT NULL,
      type TEXT,
      FOREIGN KEY (employe_id) REFERENCES employes(id)
      )  
""")

#Table des présences résumés(une ligne = un employé, un jour)
cur.execute ("""
CREATE TABLE IF NOT EXISTS presences (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      employe_id INTEGER NOT NULL,
      date TEXT NOT NULL,
      heure_arrivee TEXT,
      heure_depart TEXT,
      statut TEXT,
      FOREIGN KEY (employe_id) REFERENCES employes(id)
) 
""")

conn.commit()
conn.close ()

print ("Base de données créée  avec succès : gestion_absences.db")