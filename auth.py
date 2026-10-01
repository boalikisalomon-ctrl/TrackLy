import sqlite3
import re
import unicodedata
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

DB_PATH = "gestion_absences.db"
DOMAINE_EMAIL = "entreprise.com"


class Utilisateur(UserMixin):
    def __init__(self, id, identifiant, email, role, employe_id=None, nom=None, service=None, mot_de_passe_clair=None):
        self.id = id
        self.identifiant = identifiant
        self.email = email
        self.role = role
        self.employe_id = employe_id
        self.nom = nom
        self.service = service
        self.mot_de_passe_clair = mot_de_passe_clair

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_employe(self):
        return self.role == "employe"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialiser_tables_auth():
    """
    Initialise la table utilisateurs selon les règles de l'entreprise :
    - Un compte administrateur (admin / admin123 ou admin)
    - Comptes employés basés directement sur les noms de la pointeuse
      Identifiant : nom exact enregistré sur la pointeuse (ex: Anselme, chaffIJUNIOR)
      Mot de passe : empreinte + ID (ex: empreinte1, empreinte2, empreinte18...)
    """
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS utilisateurs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identifiant TEXT UNIQUE NOT NULL,
            email TEXT,
            mot_de_passe_hash TEXT NOT NULL,
            mot_de_passe_clair TEXT,
            role TEXT NOT NULL DEFAULT 'employe',
            employe_id INTEGER,
            date_creation TEXT,
            FOREIGN KEY (employe_id) REFERENCES employes(id)
        )
    """)

    # 1. Compte administrateur unique
    cur.execute("SELECT id FROM utilisateurs WHERE role = 'admin'")
    admin_row = cur.fetchone()
    if not admin_row:
        mdp_admin = "admin123"
        cur.execute("""
            INSERT INTO utilisateurs (identifiant, email, mot_de_passe_hash, mot_de_passe_clair, role, employe_id, date_creation)
            VALUES (?, ?, ?, ?, 'admin', NULL, ?)
        """, (
            "admin",
            f"admin@{DOMAINE_EMAIL}",
            generate_password_hash(mdp_admin),
            mdp_admin,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        print("Compte administrateur créé : admin / admin123")

    # 2. Comptes employés basés sur la pointeuse : nom + empreinte+ID
    cur.execute("SELECT id, nom FROM employes")
    employes = cur.fetchall()

    for emp in employes:
        emp_id = emp["id"]
        emp_nom = emp["nom"]
        mdp_employe = f"empreinte{emp_id}"
        email_employe = f"{emp_nom}@{DOMAINE_EMAIL}"

        cur.execute("SELECT id FROM utilisateurs WHERE employe_id = ?", (emp_id,))
        existe = cur.fetchone()

        if not existe:
            cur.execute("""
                INSERT INTO utilisateurs (identifiant, email, mot_de_passe_hash, mot_de_passe_clair, role, employe_id, date_creation)
                VALUES (?, ?, ?, ?, 'employe', ?, ?)
            """, (
                emp_nom,
                email_employe,
                generate_password_hash(mdp_employe),
                mdp_employe,
                emp_id,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
        else:
            # Met à jour l'identifiant pour qu'il corresponde au nom de la pointeuse
            # et le mot de passe clair si besoin
            cur.execute("""
                UPDATE utilisateurs
                SET identifiant = ?, email = ?, mot_de_passe_clair = ?,
                    mot_de_passe_hash = ?
                WHERE id = ?
            """, (
                emp_nom,
                email_employe,
                mdp_employe,
                generate_password_hash(mdp_employe),
                existe["id"]
            ))

    conn.commit()
    conn.close()


def creer_ou_mettre_a_jour_compte_employe(employe_id, nom_employe):
    """
    Appelé lors de la synchronisation avec la pointeuse physique.
    Crée automatiquement le compte avec le nom et 'empreinte' + ID.
    """
    conn = get_db()
    cur = conn.cursor()

    mdp_employe = f"empreinte{employe_id}"
    email_employe = f"{nom_employe}@{DOMAINE_EMAIL}"

    cur.execute("SELECT id FROM utilisateurs WHERE employe_id = ?", (employe_id,))
    existe = cur.fetchone()

    if not existe:
        cur.execute("""
            INSERT INTO utilisateurs (identifiant, email, mot_de_passe_hash, mot_de_passe_clair, role, employe_id, date_creation)
            VALUES (?, ?, ?, ?, 'employe', ?, ?)
        """, (
            nom_employe,
            email_employe,
            generate_password_hash(mdp_employe),
            mdp_employe,
            employe_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
    else:
        cur.execute("""
            UPDATE utilisateurs
            SET identifiant = ?, email = ?
            WHERE id = ?
        """, (nom_employe, email_employe, existe["id"]))

    conn.commit()
    conn.close()


def get_utilisateur_par_id(user_id):
    """Récupère l'utilisateur pour le login_manager (session)."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT u.id, u.identifiant, u.email, u.role, u.employe_id, u.mot_de_passe_clair,
               e.nom AS employe_nom, e.service AS employe_service
        FROM utilisateurs u
        LEFT JOIN employes e ON u.employe_id = e.id
        WHERE u.id = ?
    """, (user_id,))
    row = cur.fetchone()
    conn.close()

    if row:
        nom = row["employe_nom"] if row["role"] == "employe" else "Administrateur"
        service = row["employe_service"] if row["role"] == "employe" else "Direction"
        return Utilisateur(
            id=row["id"],
            identifiant=row["identifiant"],
            email=row["email"],
            role=row["role"],
            employe_id=row["employe_id"],
            nom=nom,
            service=service,
            mot_de_passe_clair=row["mot_de_passe_clair"]
        )
    return None


def verifier_identifiants(identifiant, mot_de_passe, role_requis=None):
    """
    Vérifie les identifiants pour l'authentification :
    - Pour l'Admin : identifiant = 'admin' (ou 'admin@entreprise.com'), mot de passe = 'admin123' ou 'admin'
    - Pour l'Employé :
        * Identifiant : son nom sur la pointeuse (ex: 'Anselme', 'chaffIJUNIOR') ou son email ou son ID
        * Mot de passe : 'empreinte' + ID (ex: 'empreinte1', 'empreinte18', insensible à la casse)
    """
    ident_clean = (identifiant or "").strip()
    mdp_clean = (mot_de_passe or "").strip()

    if not ident_clean or not mdp_clean:
        return None

    conn = get_db()
    cur = conn.cursor()

    # 1. Cas Admin
    if role_requis in [None, "admin"]:
        cur.execute("""
            SELECT * FROM utilisateurs
            WHERE role = 'admin'
              AND (LOWER(identifiant) = LOWER(?) OR LOWER(email) = LOWER(?))
        """, (ident_clean, ident_clean))
        admin_row = cur.fetchone()
        if admin_row:
            if check_password_hash(admin_row["mot_de_passe_hash"], mdp_clean) or (admin_row["mot_de_passe_clair"] and mdp_clean == admin_row["mot_de_passe_clair"]):
                conn.close()
                return Utilisateur(
                    id=admin_row["id"],
                    identifiant=admin_row["identifiant"],
                    email=admin_row["email"],
                    role="admin",
                    nom="Administrateur",
                    service="Direction"
                )


    # 2. Cas Employé
    if role_requis in [None, "employe"]:
        # Recherche par nom exact, nom en minuscule, ID, ou email
        cur.execute("""
            SELECT u.id, u.identifiant, u.email, u.mot_de_passe_hash, u.mot_de_passe_clair,
                   u.role, u.employe_id,
                   e.id AS emp_id, e.nom AS emp_nom, e.service AS emp_service, e.actif AS emp_actif
            FROM utilisateurs u
            JOIN employes e ON u.employe_id = e.id
            WHERE LOWER(u.identifiant) = LOWER(?)
               OR LOWER(u.email) = LOWER(?)
               OR LOWER(e.nom) = LOWER(?)
               OR CAST(e.id AS TEXT) = ?
        """, (ident_clean, ident_clean, ident_clean, ident_clean))
        emp_row = cur.fetchone()

        if emp_row:
            # Vérifier si l'employé est actif
            if emp_row["emp_actif"] == 0:
                conn.close()
                return "desactive"

            emp_id = emp_row["emp_id"]
            mdp_attendu_pattern = f"empreinte{emp_id}".lower()

            # Vérification très tolérante de "empreinte + ID" :
            # Accepte empreinte1, Empreinte1, empreinte_1, empreinte 1, ou le hash enregistré
            mdp_saisi_clean = mdp_clean.lower().replace(" ", "").replace("_", "")
            est_valide = (
                mdp_saisi_clean == mdp_attendu_pattern
                or mdp_saisi_clean == str(emp_id)
                or check_password_hash(emp_row["mot_de_passe_hash"], mdp_clean)
                or (emp_row["mot_de_passe_clair"] and mdp_clean == emp_row["mot_de_passe_clair"])
            )

            if est_valide:
                conn.close()
                return Utilisateur(
                    id=emp_row["id"],
                    identifiant=emp_row["identifiant"],
                    email=emp_row["email"],
                    role="employe",
                    employe_id=emp_id,
                    nom=emp_row["emp_nom"],
                    service=emp_row["emp_service"],
                    mot_de_passe_clair=emp_row["mot_de_passe_clair"]
                )

    conn.close()
    return None


def get_tous_comptes_employes():
    """
    Retourne la liste des employés avec leurs identifiants complets
    pour le panneau d'administration.
    """
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT u.id AS compte_id, u.identifiant, u.email, u.mot_de_passe_clair,
               e.id AS employe_id, e.nom, e.service, e.actif
        FROM utilisateurs u
        JOIN employes e ON u.employe_id = e.id
        WHERE u.role = 'employe'
        ORDER BY e.id ASC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def reinitialiser_mdp_employe(compte_id):
    """Réinitialise le mot de passe d'un employé à 'empreinte' + ID."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT employe_id FROM utilisateurs WHERE id = ?", (compte_id,))
    row = cur.fetchone()
    if row:
        nouveau_mdp = f"empreinte{row['employe_id']}"
        mdp_hash = generate_password_hash(nouveau_mdp)
        cur.execute("""
            UPDATE utilisateurs
            SET mot_de_passe_hash = ?, mot_de_passe_clair = ?
            WHERE id = ? AND role = 'employe'
        """, (mdp_hash, nouveau_mdp, compte_id))
        conn.commit()

    conn.close()


def get_compte_admin():
    """Récupère les informations du compte administrateur."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, identifiant, email, mot_de_passe_clair, date_creation FROM utilisateurs WHERE role = 'admin' LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row


def modifier_compte_admin(nouvel_identifiant=None, nouvel_email=None, nouveau_mot_de_passe=None):
    """
    Met à jour les identifiants du compte administrateur :
    - nouvel_identifiant : nom d'utilisateur personnalisé
    - nouvel_email : email personnalisé
    - nouveau_mot_de_passe : nouveau mot de passe (haché et sécurisé)
    """
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, identifiant, email, mot_de_passe_clair, mot_de_passe_hash FROM utilisateurs WHERE role = 'admin' LIMIT 1")
    admin = cur.fetchone()
    if not admin:
        conn.close()
        return False, "Compte administrateur introuvable."

    identifiant = (nouvel_identifiant or admin["identifiant"]).strip()
    email = (nouvel_email or admin["email"]).strip() if (nouvel_email or admin["email"]) else None

    if not identifiant:
        conn.close()
        return False, "L'identifiant administrateur ne peut pas être vide."

    # Vérifier les collisions d'identifiant
    cur.execute("SELECT id FROM utilisateurs WHERE LOWER(identifiant) = LOWER(?) AND id != ?", (identifiant, admin["id"]))
    if cur.fetchone():
        conn.close()
        return False, f"L'identifiant '{identifiant}' est déjà utilisé par un autre compte."

    if nouveau_mot_de_passe and nouveau_mot_de_passe.strip():
        mdp_clair = nouveau_mot_de_passe.strip()
        mdp_hash = generate_password_hash(mdp_clair)
    else:
        mdp_clair = admin["mot_de_passe_clair"]
        mdp_hash = admin["mot_de_passe_hash"]

    cur.execute("""
        UPDATE utilisateurs
        SET identifiant = ?, email = ?, mot_de_passe_hash = ?, mot_de_passe_clair = ?
        WHERE id = ?
    """, (identifiant, email, mdp_hash, mdp_clair, admin["id"]))

    conn.commit()
    conn.close()
    return True, "Identifiants administrateur mis à jour avec succès."

