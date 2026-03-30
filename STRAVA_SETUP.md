## Strava API einrichten

1. Gehe zu https://www.strava.com/settings/api
2. Erstelle eine neue App:
   - Application Name: TrainIQ
   - Category: Training
   - Website: http://localhost
   - Authorization Callback Domain: localhost
3. Kopiere Client ID und Client Secret
4. Trage in .env ein:
   STRAVA_CLIENT_ID=deine_client_id
   STRAVA_CLIENT_SECRET=dein_client_secret
   STRAVA_REDIRECT_URI=http://localhost/api/watch/strava/callback
