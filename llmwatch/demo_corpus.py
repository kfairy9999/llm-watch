"""Handwritten replies for the fictional Northline Audio support bot.

Northline is not a real company. These strings are demo copy, not captures.
"""

from __future__ import annotations

# Production-shaped traffic in the demo ledger. The 3B cost-cut is eval-only:
# it fails the gate, so it never shows up here.
SHORT_SCENARIOS = [
    {
        "route": "support",
        "user": "I bought HX-200 headphones 10 days ago and the right cup died. What is the return window?",
        "answers": {
            "llama-3.1-8b-instant": "The return window is 14 days from delivery. You're inside it, so I can start a return for the HX-200.",
            "llama-3.3-70b-versatile": "You're within the policy. Northline accepts HX-200 returns for 14 days from delivery. I can email a prepaid label if you want one.",
        },
    },
    {
        "route": "order",
        "user": "Please cancel order NL-4401. It hasn't shipped.",
        "answers": {
            "llama-3.1-8b-instant": "I cancelled NL-4401. It had not shipped, so you will not be charged.",
            "llama-3.3-70b-versatile": "Done. Order NL-4401 is cancelled before shipment, and the card authorization will drop off.",
        },
    },
    {
        "route": "product",
        "user": "What's the difference between the HX-200 and the HX-210?",
        "answers": {
            "llama-3.1-8b-instant": "HX-200 is $149 with 30 hours of battery and hybrid ANC. HX-210 is $199, adds a travel case, and runs 40 hours.",
            "llama-3.3-70b-versatile": "HX-200 ($149) has hybrid ANC and 30 hours of battery. HX-210 ($199) adds a hard travel case and runs 40 hours. Pick the 210 if you commute.",
        },
    },
    {
        "route": "support",
        "user": "My package arrived crushed. The headband is cracked.",
        "answers": {
            "llama-3.1-8b-instant": "I'm sorry it arrived crushed. I'll replace the unit. You can keep the damaged pair until the new one is delivered.",
            "llama-3.3-70b-versatile": "I'm sorry the headband arrived cracked. A replacement HX-200 ships today, and you don't need to send the crushed pair back first.",
        },
    },
    {
        "route": "account",
        "user": "How long is the warranty on the HX-200?",
        "answers": {
            "llama-3.1-8b-instant": "The HX-200 has a 2-year warranty.",
            "llama-3.3-70b-versatile": "The HX-200 warranty is 2 years from delivery. It covers manufacturing defects, not a lost or crushed unit.",
        },
    },
    {
        "route": "order",
        "user": "How many business days is standard shipping to Austin?",
        "answers": {
            "llama-3.1-8b-instant": "Standard shipping to Austin is 5 business days.",
            "llama-3.3-70b-versatile": "Standard shipping to Austin is 5 business days, not counting the day the label is created.",
        },
    },
    {
        "route": "account",
        "user": "Send the invoice for order NL-4401, but don't read my email back.",
        "answers": {
            "llama-3.1-8b-instant": "I requested the NL-4401 invoice. I won't repeat your email address here.",
            "llama-3.3-70b-versatile": "The invoice for NL-4401 is queued to the address on file. I'm not echoing the email in this chat.",
        },
    },
    {
        "route": "product",
        "user": "Give me 3 steps to reset HX-200 firmware.",
        "answers": {
            "llama-3.1-8b-instant": "1. Hold the power button for 12 seconds\n2. Plug in the USB-C cable\n3. Wait for the amber LED to turn white",
            "llama-3.3-70b-versatile": "1. Hold power for 12 seconds until the LED flashes\n2. Connect USB-C power\n3. Wait until the LED turns solid white, then pair again",
        },
    },
    {
        "route": "product",
        "user": "Can I use the HX-200 charger in a 220V hotel?",
        "answers": {
            "llama-3.1-8b-instant": "Yes. The USB-C supply accepts 100-240V. You only need a plug adapter, not a converter.",
            "llama-3.3-70b-versatile": "Yes. The included supply is 100-240V, so a 220V hotel is fine with a plug adapter. You do not need a voltage converter.",
        },
    },
]

SUMMARIZE = {
    "route": "summarize",
    "answers": {
        "llama-3.1-8b-instant": "The customer reports left-cup dropouts on an HX-200 and wants a warranty replacement. The order id still needs to be confirmed.",
        "llama-3.3-70b-versatile": "Thread summary: intermittent left-cup audio on an HX-200, several order ids mentioned, customer asked for a warranty swap. Next step is to confirm one order id and ship a replacement under the 2-year warranty.",
    },
}

SYSTEM_PROMPT = (
    "You are the Northline Audio support assistant. Northline is a fictional company "
    "used for demo data. Be concise and do not invent policies beyond the product sheet."
)


def summarize_thread(index: int) -> str:
    """A long, obviously synthetic transcript so a few calls carry real token weight."""
    lines = [
        "Summarize this support thread. The transcript is synthetic demo text.",
    ]
    for turn in range(28):
        order = f"NL-44{(index + turn) % 90:02d}"
        lines.append(
            f"Customer: The left cup on my HX-200 cuts out after {20 + turn} minutes. I mentioned order {order}."
        )
        lines.append(
            "Agent: I can replace the unit under the 2-year warranty. I still need one order id, not several."
        )
    lines.append("Customer: Please just ship the replacement.")
    return "\n".join(lines)
