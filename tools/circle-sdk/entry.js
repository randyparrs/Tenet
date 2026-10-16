// What the page loads when a visitor chooses "Continue with Google (Circle wallet)" (site/app.js, circle part).
import { W3SSdk } from "@circle-fin/w3s-pw-web-sdk";
import { SocialLoginProvider } from "@circle-fin/w3s-pw-web-sdk/dist/src/types";
window.TenetCircleSdk = { W3SSdk, SocialLoginProvider };
