import os
import re
import time
from PyPDF2 import PdfReader
from docx import Document
import google.generativeai as genai
import streamlit as st
import pandas as pd
import shutil
import io

# Configuration de l'interface utilisateur Streamlit
st.set_page_config(layout="wide")  # Utiliser toute la largeur de la page

st.markdown(
    """
    <style>
    .title {
        text-align: center;
        font-size: 2.5em;
        color: #007bff; /* Bleu Bootstrap */
    }
    .subtitle {
        text-align: center;
        font-size: 1.5em;
        color: #6c757d; /* Gris Bootstrap */
    }
    .stTextInput > label,
    .stTextArea > label,
    .stFileUploader > div > div:first-child {
        text-align: left !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown("<h1 class='title'>Application de Sélection de CV</h1>", unsafe_allow_html=True)
st.markdown("<h2 class='subtitle'>Optimisez votre processus de recrutement avec l'IA</h2>", unsafe_allow_html=True)

# Initialize session state
if 'job_title' not in st.session_state:
    st.session_state['job_title'] = ""
if 'job_experience' not in st.session_state:
    st.session_state['job_experience'] = ""
if 'job_description' not in st.session_state:
    st.session_state['job_description'] = ""
if 'resume_text' not in st.session_state:
    st.session_state['resume_text'] = None
if 'filename' not in st.session_state:
    st.session_state['filename'] = None
if 'chat_history' not in st.session_state:
    st.session_state['chat_history'] = []  # Store chat history
# Input method selection
# st.markdown("<h3 style='text-align: left;'>Méthode de saisie des détails du poste:</h3>", unsafe_allow_html=True)
input_method = st.radio("", ["Lien URL", "Saisir manuellement"])

if input_method == "Lien URL":
    # URL Scraping Form for Job Details
    with st.form(key="url_form"):
        url = st.text_input("Entrez l'URL pour extraire les détails du poste:")
        submit_url = st.form_submit_button("Extraire les détails du poste")

        if submit_url and url:
            import requests
            from bs4 import BeautifulSoup

            try:
                response = requests.get(url)
                soup = BeautifulSoup(response.content, "html.parser")

                # **Adapt these selectors to your specific webpage structure.**
                st.session_state['job_title'] = soup.find('h1').text if soup.find('h1') else "Titre du poste non trouvé"
                st.session_state['job_experience'] = soup.find('div', class_='card-wrapper-inner').text.strip().replace('\n', '') if soup.find('div', class_='card-wrapper-inner') else "Expérience professionnelle non trouvée"
                st.session_state['job_description'] = soup.find('div', class_='list-style-editor').text if soup.find('div', class_='list-style-editor') else "Description du poste non trouvée"

                # Display scraped data in Streamlit
                st.subheader("Détails du poste extraits:")
                st.write(f"**Titre du poste:** {st.session_state['job_title']}")
                st.write(f"**Expérience requise:** {st.session_state['job_experience']}")
                st.write(f"**Description du poste:** {st.session_state['job_description']}")

                st.success("Détails du poste extraits avec succès depuis l'URL!")

            except Exception as e:
                st.error(f"Erreur lors de l'extraction de l'URL: {e}")
        elif submit_url and not url:
            st.warning("Veuillez entrer une URL valide.")
elif input_method == "Saisir manuellement":
    # Manual Input Form for Job Details
    st.session_state['job_title'] = st.text_input("Entrez le titre de l'offre:", value=st.session_state['job_title'])
    st.session_state['job_experience'] = st.text_area("Entrez les informations sur le profil recherché (Expérience, Formation):", value=st.session_state['job_experience'])
    st.session_state['job_description'] = st.text_area("Entrez la description du poste:", value=st.session_state['job_description'])
else:
    st.warning("Sélectionnez une méthode de saisie (Manuelle ou URL).")

# Télécharger les fichiers
st.markdown("<h3 style='text-align: left;'>Téléversement des CV:</h3>", unsafe_allow_html=True)
uploaded_files = st.file_uploader("Téléchargez les CV (PDF, DOCX)", accept_multiple_files=True, type=["pdf", "docx"])

# Display total files after upload
if uploaded_files:
    total_resume = len(uploaded_files)
    st.markdown(f"Total des CV téléchargés: {total_resume}")

# Define the target directory before processing
# Add a default value for target_directory
#target_directory = st.text_input("Veuillez saisir le chemin où les CV seront enregistrés (OPTIONNEL):", "")  # REMOVED UI ELEMENT

# Bouton pour démarrer le processus
if st.button("Démarrer la Sélection"):
    # API Keys from Streamlit Secrets
    api_keys = [
        st.secrets["api_keys"]["key1"],
        st.secrets["api_keys"]["key2"],
        st.secrets["api_keys"]["key3"],
        st.secrets["api_keys"]["key4"],
        st.secrets["api_keys"]["key5"],
    ]

    # Track the last used API key index
    api_key_index = 0

    # Function to set API key and configure the model in order
    def configure_api_key():
        global api_key_index
        while api_key_index < len(api_keys):
            try:
                key = api_keys[api_key_index]  # Select the current API key
                genai.configure(api_key=key)
                model = genai.GenerativeModel('gemini-1.5-flash')  # Configure the model with the API key
                return model
            except Exception as e:
                st.error(f"Failed to configure API with key {key}: {e}")
                api_key_index += 1  # Move to the next API key
                continue
        # If all keys fail, show a message and return None
        st.error("Sorry, the service is temporarily unavailable. Please try again later.")
        return None  # If all keys fail

    # Initialize the model using the first working API key
    model = configure_api_key()
    if model is None:
        st.stop()


    # Limitation du débit et total des requêtes (Vous pouvez ajuster ces valeurs)
    MAX_REQUESTS_PER_MINUTE = 15
    MAX_TOTAL_REQUESTS = 1500
    total_requests = 0
    start_time = time.time()
    files_processed = 0

    # Initialiser une liste pour stocker les résultats pour le tableau
    results = []

    # Add a progress bar
    progress_bar = st.progress(0)
    total_files = len(uploaded_files)

    # --- Fonctions ---

    # Fonction pour extraire le texte du PDF
    def extract_text_from_pdf(file_path):
        try:
            reader = PdfReader(file_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text()
            return text.strip()
        except Exception as e:
            st.error(f"Erreur lors de la lecture du PDF: {file_path}, {e}")
            return None

    # Fonction pour extraire le texte du DOCX
    def extract_text_from_docx(file_path):
        try:
            doc = Document(file_path)
            text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
            return text.strip()
        except Exception as e:
            st.error(f"Erreur lors de la lecture du fichier Word: {file_path}, {e}")
            return None

    # Fonction pour évaluer la pertinence du CV en fonction du profil du poste
    def evaluate_resume_with_ai(resume_text, job_title, job_experience, job_description, filename):  # Ajout du nom de fichier
        global total_requests
        if total_requests >= MAX_TOTAL_REQUESTS:
            st.warning("Limite maximale du nombre total de requêtes atteinte.")
            return None

        total_requests += 1
        # Amélioration de l'invite
        prompt = f"""
        Compte tenu des exigences suivantes pour le poste:

        Titre du poste: {job_title}
        Exigences d'expérience: {job_experience}
        Description du poste: {job_description}

        Et de ce CV (nom de fichier: {filename}):

        {resume_text}

        Analysez en profondeur le CV. Veuillez extraire les informations suivantes :
        - Nom du candidat
        - Adresse e-mail
        - Numéro de téléphone
        - Ville
        - Pays
        - Nombre total d'années d'expérience (Le nombre doit être exact et ne doit pas inclure les stages)
        - Pourcentage d'admissibilité au poste (0-100 %)
        - Commentaires détaillés (environ 3 à 5 phrases) pour justifier le % d'admissibilité, en mentionnant les forces et les faiblesses par rapport aux exigences du poste.
        - Sexe (Homme, Femme, Non spécifié)
        - Formation (Niveaux bac, bac, Bac+2, Bac+3, Bac+4, Bac+5, Bac+8)
        - Date de naissance (si mentionnée, sinon N/A)

        De plus, en vous basant sur les commentaires détaillés, générez une liste de 10 questions à poser au candidat lors d'un entretien pour évaluer plus précisément les aspects de son profil qui ne sont pas suffisamment détaillés dans son CV et qui sont pertinents pour le poste.  Formulez ces questions de manière à obtenir des réponses spécifiques et mesurables. Chaque question doit tenir sur une seule ligne.  Numérotez les questions de 1 à 10.

        Présentez la réponse dans un format de type JSON (mais sous forme de texte brut, pas de JSON réel). Assurez-vous qu'elle est analysable.

        Exemple :

        {{
          "Nom du candidat": "John Doe",
          "Adresse e-mail": "john.doe@example.com",
          "Numéro de téléphone": "+15551234567",
          "Ville": "New York",
          "Pays": "États-Unis",
          "Nombre total d'années d'expérience": "5",
          "Pourcentage d'admissibilité": "85 %",
          "Commentaires": "John possède une solide expérience en gestion de projet et correspond bien aux exigences du poste. Il manque d'expérience dans les technologies spécifiques décrites dans la description du poste, ce qui diminue le pourcentage.",
          "Questions d'entretien": [
            "1. Pouvez-vous décrire un projet où vous avez utilisé [technologie spécifique] et quels étaient les résultats?",
            "2. Comment avez-vous géré [situation spécifique] dans le passé?",
            "3. Décrivez votre expérience avec [compétence clé] et donnez un exemple concret.",
            "4. ...",
            "5. ...",
            "6. ...",
            "7. ...",
            "8. ...",
            "9. ...",
            "10. ..."
          ],
          "Sexe": "Homme",
          "Formation": "Bac+5",
          "Date de naissance": "1990-01-01"
        }}

        Veuillez répondre en français.
        """
        try:
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            st.error(f"Erreur lors de l'appel de l'IA: {e}")
            return None

    # --- Traitement des fichiers téléchargés ---
    for i, uploaded_file in enumerate(uploaded_files):
        if total_requests >= MAX_TOTAL_REQUESTS:
            st.warning("Limite maximale du nombre total de requêtes atteinte.")
            break

        filename = uploaded_file.name
        file_extension = filename.split(".")[-1].lower()
        text = None
        # Direct processing of uploaded files - no more temp directory

        try:
            # Read the file directly from uploaded_file
            if file_extension == "pdf":
                text = extract_text_from_pdf(uploaded_file)  # Pass upload file directly
                st.session_state['resume_text'] = text
                st.session_state['filename'] = filename
            elif file_extension == "docx":
                text = extract_text_from_docx(uploaded_file)  # Pass upload file directly
                st.session_state['resume_text'] = text
                st.session_state['filename'] = filename
            else:
                st.warning(f"Type de fichier non pris en charge: {filename}")
                continue  # passer au fichier suivant
        except Exception as e:
            st.error(f"Erreur lors de la lecture du fichier {filename}: {e}")
            continue

        if text:
            ai_response = evaluate_resume_with_ai(text, st.session_state['job_title'], st.session_state['job_experience'], st.session_state['job_description'], filename)

            if ai_response:  # Traiter uniquement s'il y a une réponse
                try:
                    # Extraire les données de la réponse de l'IA
                    candidate_name_search = re.search(r'"Nom du candidat":\s*"([^"]*)"', ai_response)
                    candidate_name = candidate_name_search.group(1).strip() if candidate_name_search else "N/A"
                    # Make candidate name capitalized
                    candidate_name = candidate_name.upper()
                    email = re.search(r'"Adresse e-mail":\s*"([^"]*)"', ai_response)
                    email = email.group(1) if email else "N/A"
                    phone_number = re.search(r'"Numéro de téléphone":\s*"([^"]*)"', ai_response)
                    phone_number = phone_number.group(1) if phone_number else "N/A"
                    city = re.search(r'"Ville":\s*"([^"]*)"', ai_response)
                    city = city.group(1) if city else "N/A"
                    country = re.search(r'"Pays":\s*"([^"]*)"', ai_response)
                    country = country.group(1) if country else "N/A"
                    experience = re.search(r'"Nombre total d\'années d\'expérience":\s*"([^"]*)"', ai_response)
                    experience = experience.group(1) if experience else "N/A"
                    admissibility_str = re.search(r'"Pourcentage d\'admissibilité":\s*"([^"]*)"', ai_response)
                    admissibility_str = admissibility_str.group(1) if admissibility_str else "0%"  # Default to 0%
                    admissibility = int(admissibility_str.replace('%', ''))  # Extract percentage as integer

                    # Handle potential NoneType for Comments
                    comments_match = re.search(r'"Commentaires":\s*"([^"]*)"', ai_response)
                    comments = comments_match.group(1) if comments_match else "N/A"

                    # Extract interview questions
                    questions_match = re.search(r'"Questions d\'entretien":\s*\[([^\]]*)\]', ai_response)
                    questions_str = questions_match.group(1) if questions_match else ""

                    # Properly split and clean up the questions
                    questions = [q.strip().strip('"') for q in questions_str.split(',') if q.strip()]

                    gender = re.search(r'"Sexe":\s*"([^"]*)"', ai_response)
                    gender = gender.group(1) if gender else "N/A"
                    formation = re.search(r'"Formation":\s*"([^"]*)"', ai_response)
                    formation = formation.group(1) if formation else "N/A"
                    date_naissance = re.search(r'"Date de naissance":\s*"([^"]*)"', ai_response)
                    date_naissance = date_naissance.group(1) if date_naissance else "N/A"

                    # Construct the new filename
                    new_filename = f"{admissibility}% - {candidate_name}.{file_extension}"

                    # NEW SECTION: Handle target_directory only if defined elsewhere


                    # Add results
                    results.append({
                        "Nom du fichier": new_filename,  # Store the new filename
                        "Nom du candidat": candidate_name,
                        "Job Title": st.session_state['job_title'],
                        "Admissibilité (%)": admissibility,
                        "Commentaires": comments,
                        "Questions d'entretien": questions,
                        "Gender": gender,
                        "Formation": formation,
                        "Ville": city,
                        "Pays": country,
                        "Expérience (Années)": experience,
                        "Date de naissance": date_naissance,
                        "Téléphone": phone_number,
                        "E-mail": email

                    })

                except Exception as e:
                    st.error(f"Erreur lors de l'analyse de la réponse de l'IA pour {filename}: {e}. La réponse était: {ai_response}")
            else:
                st.warning(f"Aucune réponse de l'IA pour {filename}")
        else:
            st.warning(f"Échec de l'extraction du texte de {filename}")

        files_processed += 1

        # Appliquer la limitation du débit
        if files_processed % MAX_REQUESTS_PER_MINUTE == 0:
            elapsed_time = time.time() - start_time
            if elapsed_time < 60:
                time_to_wait = 60 - elapsed_time
                st.info(f"Limite de débit atteinte. Attente de {time_to_wait:.2f} secondes...")
                time.sleep(time_to_wait)
            start_time = time.time()

        # Update the progress bar
        progress_bar.progress((i + 1) / total_files)

    st.success("Sélection de CV terminée!")

    # Créer un DataFrame Pandas à partir des résultats
    df = pd.DataFrame(results)

    # Check if all expected columns are present in the DataFrame
    expected_columns = ["Nom du fichier", "Nom du candidat", "Job Title", "Admissibilité (%)", "Commentaires", "Questions d'entretien", "Gender",
                        "Formation", "Ville", "Pays", "Expérience (Années)", "Date de naissance", "Téléphone", "E-mail"]
    missing_columns = [col for col in expected_columns if col not in df.columns]

    if missing_columns:
        st.error(
            f"The following columns are missing in the DataFrame: {missing_columns}. Please check the AI response parsing logic.")
    else:
        # Reorder the dataframe columns
        df = df[expected_columns]  # Use the same list defined above

        # Afficher le tableau dans Streamlit
        st.dataframe(df)

        # Function to convert DataFrame to Excel
        def to_excel(df):
            output = io.BytesIO()
            writer = pd.ExcelWriter(output, engine='xlsxwriter')
            df.to_excel(writer, sheet_name='Results', index=False)
            writer.close()
            processed_data = output.getvalue()
            return processed_data

        # Download button
        excel_file = to_excel(df)
        st.download_button(
            label="Télécharger les résultats au format Excel",
            data=excel_file,
            file_name='resume_selection_results.xlsx',
            mime='application/vnd.ms-excel'
        )

    # Chat with AI Section - Iterative Chat
    if st.session_state['resume_text']:
        st.markdown("<h3 style='text-align: left;'>Chattez avec l'IA concernant le CV de:</h3>", unsafe_allow_html=True)
        st.markdown(f"Fichier: {st.session_state['filename']}")  # Display filename

        # Display Chat History
        for message in st.session_state['chat_history']:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        user_question = st.chat_input("Posez votre question sur ce CV:")

        if user_question:
            st.session_state['chat_history'].append({"role": "user", "content": user_question})
            with st.chat_message("user"):
                st.markdown(user_question)

            # Prepare the prompt with the resume text, job details, and chat history
            chat_prompt = f"""
            Vous êtes un assistant spécialisé dans l'analyse de CV.

            Informations sur le poste:
            Titre du poste: {st.session_state['job_title']}
            Exigences d'expérience: {st.session_state['job_experience']}
            Description du poste: {st.session_state['job_description']}

            CV:
            {st.session_state['resume_text']}

            Historique de la conversation:
            """
            for message in st.session_state['chat_history']:
                chat_prompt += f"\n{message['role']}: {message['content']}"

            chat_prompt += "\nassistant:" # signal that gemini should answer

            try:
                # Use the same model instance to generate the response
                chat_response = model.generate_content(chat_prompt)
                ai_answer = chat_response.text
                st.session_state['chat_history'].append({"role": "assistant", "content": ai_answer})
                with st.chat_message("assistant"):
                    st.markdown(ai_answer)  # Display the AI's response
            except Exception as e:
                st.error(f"Erreur lors de la communication avec l'IA: {e}")

    else:
        st.info("Veuillez d'abord télécharger et traiter un CV pour activer cette fonctionnalité.")
