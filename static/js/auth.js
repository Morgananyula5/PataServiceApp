// Import modular Firebase SDKs
import { getApp } from "https://www.gstatic.com/firebasejs/12.3.0/firebase-app.js";
import { getAuth, signInWithPhoneNumber, RecaptchaVerifier } from "https://www.gstatic.com/firebasejs/12.3.0/firebase-auth.js";
import { initializeAppCheck, ReCaptchaV3Provider } from "https://www.gstatic.com/firebasejs/12.3.0/firebase-app-check.js";

// Firebase configuration (not used for init, but for reference)
const firebaseConfig = {
  apiKey: "AIzaSyCKTC4AzQmsu41m0Fjo7pxvzH1u5QpFe7o",
  authDomain: "pataservice-web-app.firebaseapp.com",
  projectId: "pataservice-web-app",
  storageBucket: "pataservice-web-app.firebasestorage.app",
  messagingSenderId: "567016158411",
  appId: "1:567016158411:web:53028371be0f507a4a974e",
  measurementId: "G-LX4XQ9MTY0"
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  // Ensure phone form listener is attached even if Firebase init fails
  attachPhoneFormListener();

  try {
    // Get the existing app (initialized in HTML for analytics)
    const app = getApp();
    const auth = getAuth(app);

    // Initialize App Check with reCAPTCHA v3 (enforces v3 for phone auth)
    const appCheck = initializeAppCheck(app, {
      provider: new ReCaptchaV3Provider('6LcBIdYrAAAAALZwMdXMcKuma5faes-hJLlnJdW4'),
      isTokenAutoRefreshEnabled: true  // Enforce auto refresh in production
    });

    console.log('Firebase and App Check initialized successfully');
  } catch (error) {
    console.error('Firebase/App Check initialization error (non-fatal for phone auth):', error.message);
    // Listener already attached outside try-catch
  }
});

function attachPhoneFormListener() {
  const phoneForm = document.getElementById('phoneSignupForm');
  if (!phoneForm) {
    console.error('Phone form not found');
    return;
  }

  phoneForm.addEventListener('submit', (e) => {
    e.preventDefault();
    e.stopPropagation(); // Extra prevent to stop bubbling
    console.log('Phone signup form submitted - prevented default');

    const phoneInput = document.getElementById('phone');
    const phoneError = document.getElementById('phoneError');
    const phoneValue = phoneInput.value.trim();

    // Validate phone number (E.164 format)
    const phoneRegex = /^\+[1-9]\d{1,14}$/;
    if (!phoneRegex.test(phoneValue)) {
      phoneError.textContent = 'Please enter a valid phone number in E.164 format (e.g., +12025550123).';
      phoneError.style.display = 'block';
      console.log('Invalid phone number:', phoneValue);
      return;
    }
    phoneError.style.display = 'none';

    // Show spinner, hide other containers - ensure choice stays hidden
    document.getElementById('spinner').style.display = 'flex';
    document.getElementById('phoneSignupForm').style.display = 'none';
    document.getElementById('choice-container').style.display = 'none'; // Explicitly hide choice
    document.getElementById('emailSignupForm').style.display = 'none';
    document.getElementById('verificationContainer').style.display = 'none';

    try {
      const app = getApp();
      const auth = getAuth(app);
      const recaptchaVerifier = new RecaptchaVerifier(auth, 'recaptcha-container', {
        'size': 'invisible',
        'callback': (response) => {
          console.log('reCAPTCHA solved');
        }
      });

      signInWithPhoneNumber(auth, phoneValue, recaptchaVerifier)
        .then((confirmationResult) => {
          window.confirmationResult = confirmationResult;
          document.getElementById('spinner').style.display = 'none';
          document.getElementById('displayPhone').textContent = phoneValue;
          document.getElementById('verificationContainer').style.display = 'block';
          console.log('SMS sent to:', phoneValue);
        })
        .catch((error) => {
          console.error('SMS send error:', error.code, error.message);
          document.getElementById('spinner').style.display = 'none';
          document.getElementById('phoneSignupForm').style.display = 'block';
          // Keep choice hidden
          document.getElementById('choice-container').style.display = 'none';
          phoneError.textContent = 'Error sending code: ' + error.message + '. Please check your phone number and try again.';
          phoneError.style.display = 'block';
          recaptchaVerifier.clear();
        });
    } catch (error) {
      console.error('Runtime error in phone auth:', error);
      document.getElementById('spinner').style.display = 'none';
      document.getElementById('phoneSignupForm').style.display = 'block';
      document.getElementById('choice-container').style.display = 'none';
      phoneError.textContent = 'Initialization error: ' + error.message + '. Please refresh and try again.';
      phoneError.style.display = 'block';
    }
  });

  console.log('Phone form listener attached');
}

// Verify code (attach separately to avoid init issues)
document.addEventListener('DOMContentLoaded', () => {
  const verifyButton = document.getElementById('verifyButton');
  if (verifyButton) {
    verifyButton.addEventListener('click', () => {
      console.log('Verify button clicked');
      const codeInput = document.getElementById('verificationCodeInput');
      const verificationError = document.getElementById('verificationError');
      const codeValue = codeInput.value.trim();

      if (codeValue.length !== 6) {
        verificationError.textContent = 'Please enter a valid 6-digit code.';
        verificationError.style.display = 'block';
        console.log('Invalid code length:', codeValue);
        return;
      }
      verificationError.style.display = 'none';

      if (!window.confirmationResult) {
        verificationError.textContent = 'No verification in progress. Please request a new code.';
        verificationError.style.display = 'block';
        return;
      }

      document.getElementById('spinner').style.display = 'flex';
      document.getElementById('verificationContainer').style.display = 'none';

      window.confirmationResult.confirm(codeValue)
        .then((result) => {
          result.user.getIdToken().then((idToken) => {
            // Get form data
            const password = document.getElementById('phone-password').value;
            const role = document.getElementById('phone-role').value;
            const phone = document.getElementById('phone').value;

            console.log('Sending to backend:', { idToken, password, role, phone });

            // Send to backend
            fetch(window.location.origin + '/verify-user', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ idToken, password, role, phone })
            })
            .then(response => response.json())
            .then(data => {
              document.getElementById('spinner').style.display = 'none';
              if (data.success) {
                console.log('Verification successful, redirecting...');
                alert('Verified! Welcome!');
                if (role === 'customer') {
                  window.location.href = '/customer_dashboard';
                } else {
                  window.location.href = '/provider_dashboard';
                }
              } else {
                document.getElementById('verificationContainer').style.display = 'block';
                verificationError.textContent = 'Verification failed: ' + data.error;
                verificationError.style.display = 'block';
                console.error('Backend verification failed:', data.error);
              }
            })
            .catch(error => {
              document.getElementById('spinner').style.display = 'none';
              document.getElementById('verificationContainer').style.display = 'block';
              verificationError.textContent = 'Error contacting server: ' + error.message;
              verificationError.style.display = 'block';
              console.error('Backend fetch error:', error.message);
            });
          });
        })
        .catch((error) => {
          document.getElementById('spinner').style.display = 'none';
          document.getElementById('verificationContainer').style.display = 'block';
          verificationError.textContent = 'Error verifying code: ' + error.message;
          verificationError.style.display = 'block';
          console.error('Verification error:', error.message);
        });
    });
    console.log('Verify button listener attached');
  }
});

// Resend code (attach separately)
document.addEventListener('DOMContentLoaded', () => {
  const resendButton = document.getElementById('resendButton');
  if (resendButton) {
    resendButton.addEventListener('click', () => {
      console.log('Resend button clicked');
      const phoneInput = document.getElementById('phone');
      const phoneError = document.getElementById('phoneError');
      const phoneValue = phoneInput.value.trim();

      if (!phoneValue) {
        phoneError.textContent = 'Phone number not found. Please go back and enter it.';
        phoneError.style.display = 'block';
        return;
      }

      document.getElementById('spinner').style.display = 'flex';
      document.getElementById('verificationContainer').style.display = 'none';

      try {
        const app = getApp();
        const auth = getAuth(app);
        const recaptchaVerifier = new RecaptchaVerifier(auth, 'recaptcha-container', {
          'size': 'invisible',
          'callback': (response) => {
            console.log('reCAPTCHA solved for resend');
          }
        });

        signInWithPhoneNumber(auth, phoneValue, recaptchaVerifier)
          .then((confirmationResult) => {
            window.confirmationResult = confirmationResult;
            document.getElementById('spinner').style.display = 'none';
            document.getElementById('displayPhone').textContent = phoneValue;
            document.getElementById('verificationContainer').style.display = 'block';
            alert('Verification code resent to your phone.');
            console.log('SMS resent to:', phoneValue);
          })
          .catch((error) => {
            console.error('Resend error:', error.code, error.message);
            document.getElementById('spinner').style.display = 'none';
            document.getElementById('verificationContainer').style.display = 'block';
            phoneError.textContent = 'Error resending code: ' + error.message;
            phoneError.style.display = 'block';
            recaptchaVerifier.clear();
          });
      } catch (error) {
        console.error('Runtime error in resend:', error);
        document.getElementById('spinner').style.display = 'none';
        document.getElementById('verificationContainer').style.display = 'block';
        phoneError.textContent = 'Resend error: ' + error.message;
        phoneError.style.display = 'block';
      }
    });
    console.log('Resend button listener attached');
  }
});