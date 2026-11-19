# Security policy

## Reporting a problem

Please do not open a public issue for a security problem.

Use GitHub's private vulnerability reporting: on this repository's **Security** tab, choose **Report a vulnerability**. If that option is not available to you, open an issue titled "Security contact request" with no details in it, and a private route will be arranged.

## Scope

icslint runs locally on calendar files you give it; it makes no network calls and never edits the files it checks. A security problem here would be something a crafted .ics file can make the tool do beyond reading that file — for example a hang or memory blow-up on pathological folding, or a crash that is not a clean one-line error.
