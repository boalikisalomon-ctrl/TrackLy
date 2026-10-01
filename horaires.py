import sqlite3
from datetime import datetime

DB_PATH = "gestion_absences.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialiser_table_horaires():
    """
    Initialise et synchronise la table horaires_employes avec les colonnes
    requises pour la gestion des cours du jour / cours du soir, de la première
    connexion et des autorisations de modification.
    """
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS horaires_employes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employe_id INTEGER UNIQUE NOT NULL,
            type_programme TEXT DEFAULT 'jour',
            heure_debut TEXT NOT NULL DEFAULT '08:00',
            heure_fin TEXT NOT NULL DEFAULT '16:00',
            jours_semaine TEXT DEFAULT 'Lundi-Vendredi',
            autoriser_modification INTEGER DEFAULT 0,
            demande_modification INTEGER DEFAULT 0,
            date_mise_a_jour TEXT,
            programme_configure INTEGER DEFAULT 0,
            demande_statut TEXT DEFAULT 'aucune',
            demande_type TEXT,
            demande_heure_debut TEXT,
            demande_heure_fin TEXT,
            demande_jours TEXT,
            demande_motif TEXT,
            demande_date TEXT,
            FOREIGN KEY (employe_id) REFERENCES employes(id)
        )
    """)

    # Vérification et ajout automatique des colonnes manquantes (au cas où la table préexistait)
    cur.execute("PRAGMA table_info(horaires_employes)")
    colonnes_existantes = [row["name"] for row in cur.fetchall()]

    colonnes_a_ajouter = {
        "demande_statut": "TEXT DEFAULT 'aucune'",
        "demande_type": "TEXT",
        "demande_heure_debut": "TEXT",
        "demande_heure_fin": "TEXT",
        "demande_jours": "TEXT",
        "demande_motif": "TEXT",
        "demande_date": "TEXT",
        "programme_configure": "INTEGER DEFAULT 0"
    }

    for col, definition in colonnes_a_ajouter.items():
        if col not in colonnes_existantes:
            try:
                cur.execute(f"ALTER TABLE horaires_employes ADD COLUMN {col} {definition}")
            except Exception as e:
                print(f"Note migration colonne {col}: {e}")

    # Synchronisation : s'assurer que chaque employé a une ligne dans horaires_employes
    cur.execute("SELECT id, nom FROM employes")
    employes = cur.fetchall()

    for emp in employes:
        emp_id = emp["id"]
        cur.execute("SELECT id FROM horaires_employes WHERE employe_id = ?", (emp_id,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO horaires_employes (
                    employe_id, type_programme, heure_debut, heure_fin,
                    jours_semaine, autoriser_modification, programme_configure,
                    demande_statut, date_mise_a_jour
                ) VALUES (?, 'jour', '08:00', '16:00', 'Lundi-Vendredi', 0, 0, 'aucune', ?)
            """, (emp_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    conn.commit()
    conn.close()


def get_horaire_employe(employe_id):
    """
    Récupère le programme horaire complet d'un employé.
    Garantit l'existence d'un enregistrement par défaut si inexistant.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM horaires_employes WHERE employe_id = ?", (employe_id,))
    row = cur.fetchone()

    if not row:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""
            INSERT INTO horaires_employes (
                employe_id, type_programme, heure_debut, heure_fin,
                jours_semaine, autoriser_modification, programme_configure,
                demande_statut, date_mise_a_jour
            ) VALUES (?, 'jour', '08:00', '16:00', 'Lundi-Vendredi', 0, 0, 'aucune', ?)
        """, (employe_id, now_str))
        conn.commit()
        cur.execute("SELECT * FROM horaires_employes WHERE employe_id = ?", (employe_id,))
        row = cur.fetchone()

    conn.close()
    return dict(row) if row else None


def normaliser_heure(heure_str):
    """Normalise une heure au format HH:MM (ajoute zéro si besoin, ex: 8:00 -> 08:00)."""
    if not heure_str:
        return "08:00"
    h = heure_str.strip()
    parties = h.split(":")
    if len(parties) >= 2:
        return f"{int(parties[0]):02d}:{int(parties[1]):02d}"
    return h


def enregistrer_programme_initial(employe_id, type_programme, heure_debut, heure_fin, jours_semaine):
    """
    Enregistre les horaires de l'employé lors de sa PREMIÈRE connexion.
    Marque le programme comme configuré (programme_configure = 1).
    """
    h_deb = normaliser_heure(heure_debut)
    h_fin = normaliser_heure(heure_fin)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE horaires_employes
        SET type_programme = ?,
            heure_debut = ?,
            heure_fin = ?,
            jours_semaine = ?,
            programme_configure = 1,
            date_mise_a_jour = ?
        WHERE employe_id = ?
    """, (type_programme, h_deb, h_fin, jours_semaine, now_str, employe_id))

    # Synchroniser également la table employes
    cur.execute("""
        UPDATE employes
        SET type_programme = ?,
            heure_debut_prevue = ?,
            heure_fin_prevue = ?,
            jours_travail = ?,
            programme_defini = 1
        WHERE id = ?
    """, (type_programme, h_deb, h_fin, jours_semaine, employe_id))

    conn.commit()
    conn.close()
    return True


def modifier_programme(employe_id, type_programme, heure_debut, heure_fin, jours_semaine, par_admin=False):
    """
    Modifie le programme d'un employé.
    Si ce n'est pas l'admin, vérifie que l'employé bénéficie de l'autorisation accordée par l'admin.
    """
    conn = get_db()
    cur = conn.cursor()

    if not par_admin:
        cur.execute("SELECT autoriser_modification FROM horaires_employes WHERE employe_id = ?", (employe_id,))
        row = cur.fetchone()
        if not row or not row["autoriser_modification"]:
            conn.close()
            return False, "Vous n'avez pas l'autorisation de modifier vos horaires directement. Veuillez faire une demande à l'administrateur."

    h_deb = normaliser_heure(heure_debut)
    h_fin = normaliser_heure(heure_fin)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        UPDATE horaires_employes
        SET type_programme = ?,
            heure_debut = ?,
            heure_fin = ?,
            jours_semaine = ?,
            programme_configure = 1,
            demande_statut = 'aucune',
            date_mise_a_jour = ?
        WHERE employe_id = ?
    """, (type_programme, h_deb, h_fin, jours_semaine, now_str, employe_id))

    cur.execute("""
        UPDATE employes
        SET type_programme = ?,
            heure_debut_prevue = ?,
            heure_fin_prevue = ?,
            jours_travail = ?,
            programme_defini = 1
        WHERE id = ?
    """, (type_programme, h_deb, h_fin, jours_semaine, employe_id))

    conn.commit()
    conn.close()
    return True, "Programme mis à jour avec succès."


def soumettre_demande_modification(employe_id, type_programme, heure_debut, heure_fin, jours_semaine, motif):
    """
    Soumet une demande de modification d'horaires à l'administrateur.
    L'administrateur pourra l'accepter ou la refuser.
    """
    h_deb = normaliser_heure(heure_debut)
    h_fin = normaliser_heure(heure_fin)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE horaires_employes
        SET demande_statut = 'en_attente',
            demande_type = ?,
            demande_heure_debut = ?,
            demande_heure_fin = ?,
            demande_jours = ?,
            demande_motif = ?,
            demande_date = ?
        WHERE employe_id = ?
    """, (type_programme, h_deb, h_fin, jours_semaine, motif or "Changement d'emploi du temps", now_str, employe_id))

    conn.commit()
    conn.close()
    return True


def traiter_demande_horaire(employe_id, decision):
    """
    Traite la demande d'horaires par l'administrateur ('accepter' ou 'refuser').
    """
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM horaires_employes WHERE employe_id = ?", (employe_id,))
    horaire = cur.fetchone()

    if not horaire or horaire["demande_statut"] != "en_attente":
        conn.close()
        return False, "Aucune demande en attente pour cet employé."

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if decision == "accepter":
        cur.execute("""
            UPDATE horaires_employes
            SET type_programme = demande_type,
                heure_debut = demande_heure_debut,
                heure_fin = demande_heure_fin,
                jours_semaine = demande_jours,
                programme_configure = 1,
                demande_statut = 'approuvee',
                date_mise_a_jour = ?
            WHERE employe_id = ?
        """, (now_str, employe_id))

        cur.execute("""
            UPDATE employes
            SET type_programme = ?,
                heure_debut_prevue = ?,
                heure_fin_prevue = ?,
                jours_travail = ?,
                programme_defini = 1
            WHERE id = ?
        """, (horaire["demande_type"], horaire["demande_heure_debut"],
              horaire["demande_heure_fin"], horaire["demande_jours"], employe_id))

        msg = "Demande acceptée et nouveaux horaires appliqués."
    else:
        cur.execute("""
            UPDATE horaires_employes
            SET demande_statut = 'refusee',
                date_mise_a_jour = ?
            WHERE employe_id = ?
        """, (now_str, employe_id))
        msg = "Demande refusée."

    conn.commit()
    conn.close()
    return True, msg


def basculer_autorisation_modification(employe_id, autoriser=None):
    """
    Active ou désactive le droit pour un employé de modifier lui-même ses horaires.
    Si autoriser est None, bascule l'état actuel (0 -> 1 ou 1 -> 0).
    """
    conn = get_db()
    cur = conn.cursor()

    if autoriser is None:
        cur.execute("SELECT autoriser_modification FROM horaires_employes WHERE employe_id = ?", (employe_id,))
        row = cur.fetchone()
        actuel = row["autoriser_modification"] if row else 0
        nouvel_etat = 0 if actuel else 1
    else:
        nouvel_etat = 1 if autoriser else 0

    cur.execute("""
        UPDATE horaires_employes
        SET autoriser_modification = ?
        WHERE employe_id = ?
    """, (nouvel_etat, employe_id))

    cur.execute("""
        UPDATE employes
        SET autorisation_modif = ?
        WHERE id = ?
    """, (nouvel_etat, employe_id))

    conn.commit()
    conn.close()
    return nouvel_etat


def get_tous_horaires_employes():
    """
    Récupère tous les employés avec leurs informations de programme horaire,
    pour la gestion complète par l'administrateur.
    """
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT e.id AS employe_id, e.nom, e.service, e.actif,
               COALESCE(h.type_programme, e.type_programme, 'jour') AS type_programme,
               COALESCE(h.heure_debut, e.heure_debut_prevue, '08:00') AS heure_debut,
               COALESCE(h.heure_fin, e.heure_fin_prevue, '16:00') AS heure_fin,
               COALESCE(h.jours_semaine, e.jours_travail, 'Lundi-Vendredi') AS jours_semaine,
               COALESCE(h.autoriser_modification, e.autorisation_modif, 0) AS autoriser_modification,
               COALESCE(h.programme_configure, e.programme_defini, 0) AS programme_configure,
               h.demande_statut, h.demande_type, h.demande_heure_debut,
               h.demande_heure_fin, h.demande_jours, h.demande_motif, h.demande_date,
               h.date_mise_a_jour
        FROM employes e
        LEFT JOIN horaires_employes h ON e.id = h.employe_id
        ORDER BY e.nom ASC
    """)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_demandes_en_attente():
    """Récupère toutes les demandes de modification en attente d'approbation admin."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT e.id AS employe_id, e.nom, e.service,
               h.type_programme AS actuel_type,
               h.heure_debut AS actuel_debut,
               h.heure_fin AS actuel_fin,
               h.jours_semaine AS actuel_jours,
               h.demande_type, h.demande_heure_debut, h.demande_heure_fin,
               h.demande_jours, h.demande_motif, h.demande_date
        FROM horaires_employes h
        JOIN employes e ON h.employe_id = e.id
        WHERE h.demande_statut = 'en_attente'
        ORDER BY h.demande_date DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
