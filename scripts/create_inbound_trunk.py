import json
import logging
import os
import re
import subprocess
from dotenv import load_dotenv
from twilio.rest import Client


def get_env_var(var_name):
    value = os.getenv(var_name)
    if not value:
        raise RuntimeError(f"Environment variable '{var_name}' not set.")
    return value


def create_livekit_trunk(client, livekit_sip_uri):
    domain_name = f"livekit-trunk-{os.urandom(4).hex()}.pstn.twilio.com"

    trunk = client.trunking.v1.trunks.create(
        friendly_name="LiveKit Trunk",
        domain_name=domain_name,
    )

    trunk.origination_urls.create(
        sip_url=f"{livekit_sip_uri};transport=tcp",
        weight=1,
        priority=1,
        enabled=True,
        friendly_name="LiveKit SIP URI",
    )

    logging.info("Created new LiveKit Trunk.")
    return trunk


def run_lk_command(args, payload, timeout=10):
    """
    Faster subprocess execution with stdin pipe instead of temp files.
    """
    result = subprocess.run(
        args,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=timeout
    )

    if result.returncode != 0:
        logging.error(result.stderr)
        return None

    return result.stdout


def create_inbound_trunk(phone_number, livekit_url, api_key, api_secret):
    trunk_data = {
        "trunk": {
            "name": "Inbound LiveKit Trunk",
            "numbers": [phone_number]
        }
    }

    args = [
        'lk', 'sip', 'inbound', 'create', '-',
        '--url', livekit_url.replace("wss", "https"),
        '--api-key', api_key,
        '--api-secret', api_secret
    ]

    output = run_lk_command(args, trunk_data)
    if not output:
        return None

    match = re.search(r'ST_[A-Za-z0-9]+', output)
    if match:
        inbound_trunk_sid = match.group(0)
        logging.info(f"Inbound trunk created: {inbound_trunk_sid}")
        return inbound_trunk_sid

    logging.error("Inbound trunk SID not found.")
    return None


def create_dispatch_rule(trunk_sid, livekit_url, api_key, api_secret):
    dispatch_rule_data = {
        "name": "Inbound Dispatch Rule",
        "trunk_ids": [trunk_sid],
        "rule": {
            "dispatchRuleIndividual": {
                "roomPrefix": "call-"
            }
        }
    }

    args = [
        'lk', 'sip', 'dispatch-rule', 'create', '-',
        '--url', livekit_url.replace("wss", "https"),
        '--api-key', api_key,
        '--api-secret', api_secret
    ]

    output = run_lk_command(args, dispatch_rule_data)
    if output:
        logging.info("Dispatch rule created successfully.")


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    account_sid = get_env_var("TWILIO_ACCOUNT_SID")
    auth_token = get_env_var("TWILIO_AUTH_TOKEN")
    phone_number = get_env_var("TWILIO_PHONE_NUMBER")
    livekit_sip_uri = get_env_var("LIVEKIT_SIP_URI")
    livekit_url = get_env_var("LIVEKIT_URL")
    livekit_api_key = get_env_var("LIVEKIT_API_KEY")
    livekit_api_secret = get_env_var("LIVEKIT_API_SECRET")

    client = Client(account_sid, auth_token)

    # Faster lookup (limit 20 instead of full list)
    trunks = client.trunking.v1.trunks.list(limit=20)
    livekit_trunk = next(
        (t for t in trunks if t.friendly_name == "LiveKit Trunk"),
        None
    )

    if not livekit_trunk:
        livekit_trunk = create_livekit_trunk(client, livekit_sip_uri)
    else:
        logging.info("Using existing LiveKit Trunk.")

    inbound_trunk_sid = create_inbound_trunk(
        phone_number,
        livekit_url,
        livekit_api_key,
        livekit_api_secret
    )

    if inbound_trunk_sid:
        create_dispatch_rule(
            inbound_trunk_sid,
            livekit_url,
            livekit_api_key,
            livekit_api_secret
        )


if __name__ == "__main__":
    main()