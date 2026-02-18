# LENAH — Property Email Assistant (MVP)

LENAH is a Streamlit-based property email assistant that drafts and sends enquiry emails from a central Gmail inbox.

This MVP focuses on the core workflow:
- User chats with LENAH via a simple chatbot UI
- User provides their email (required) → LENAH will CC them on every enquiry
- User provides an estate agent email address
- LENAH generates a short enquiry email using OpenAI (GPT)
- LENAH sends the email via the Gmail API from the central mailbox

---

## Current MVP Features

✅ Streamlit chatbot interface  
✅ OpenAI GPT integration (structured JSON output)  
✅ Gmail API integration (send email from LENAH mailbox)  
✅ User email captured and stored per session (mandatory CC)  
✅ Recipient email must be explicitly pasted before sending  

---


