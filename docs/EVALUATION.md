# Newsroom evaluation

Run `newsroom-md11-20261020-214737` on 2026-10-20 21:53: 24 moments from simulated matchday 11, rendered in en, es, ar. Analyst `gpt-5-mini`, Host `gpt-4.1-mini`, judge `gpt-4.1-mini`.

## Quality gates

| Metric | Value | Gate | |
|---|---|---|---|
| verified rate | 100% | >= 0.9 | ✅ |
| final claim accuracy | 100% | >= 0.98 | ✅ |
| planted claim catch rate | 100% | >= 0.95 | ✅ |
| planted fabrication catch rate | 100% | >= 0.9 | ✅ |
| control false alarm rate | 0% | <= 0.1 | ✅ |
| renditions with untraceable numbers | 8% | <= 0.15 | ✅ |
| language coverage | 100% | >= 0.95 | ✅ |
| latency p95 s | 13.31 | <= 30.0 | ✅ |
| groundedness | 4.91 | >= 3.5 | ✅ |
| relevance | 5.00 | >= 3.5 | ✅ |
| coherence | 4.61 | >= 3.5 | ✅ |

## Details

- First-pass clean (no Verifier corrections needed): 88%; rewrites per item: 0.12
- Planted-error tests: 24 items; corrupted claims caught 100%, fabricated statistics caught 100%, false alarms on untouched items 0%
- Latency p50 8.7s, p95 13.3s (Analyst + Verifier + 3-language Host, end to end)
- AI judges (1-5): groundedness 4.91, relevance 5.00, coherence 4.61, fluency 4.00
- Content safety defect rates: {'hate_unfairness_defect_rate': 0.0, 'sexual_defect_rate': 0.0, 'self_harm_defect_rate': 0.0, 'violence_defect_rate': 0.0}
- Foundry evaluation run: https://ai.azure.com/resource/build/evaluation/56062c0f-939a-4a6c-8d0d-6d9d05c3715a?wsid=/subscriptions/991df65a-d37a-4d15-9414-3a448ce23817/resourceGroups/rg-footballytics-dev/providers/Microsoft.CognitiveServices/accounts/fbx-ai-5dn4hvp4nnbzs/projects/footballytics&tid=c46e3e34-90fe-4e13-9135-bdf6c03b41be

## Items

| Kind | Min | Status | Claims ok | Untraceable numbers | Latency | Headline |
|---|---|---|---|---|---|---|
| high_turnover | 1 | verified | 3/3 | 30 | 12.4s | Rahman’s early interception swings momentum to Falconridge |
| line_breaking_pass | 1 | verified | 3/3 | 18.6 | 9.8s | Early 45‑metre line‑breaking pass sets tone |
| line_breaking_pass | 1 | verified | 3/3 | – | 8.3s | Petrov’s high-risk cross breaks the deadlock pressure |
| momentum_swing | 2 | verified | 3/3 | – | 7.5s | Falconridge controls opening threat entirely |
| penalty_awarded | 2 | verified | 3/3 | – | 8.2s | Early penalty hands Rahman a game-changing chance |
| high_turnover | 3 | verified | 3/3 | – | 9.7s | Early high turnover sparks HFP counter opportunity |
| goal | 3 | verified | 3/3 | – | 7.2s | Early penalty gives Falconridge a sharp lead |
| momentum_swing | 4 | verified | 3/3 | – | 9.0s | Kingsbridge seizes early control with concentrated threat |
| goal | 4 | verified | 3/3 | – | 8.2s | Early corner header gives Kingsbridge shock lead |
| goal | 4 | verified | 3/3 | – | 13.3s | Early penalty hands Thornbury the lead |
| big_chance | 5 | verified | 3/3 | – | 15.4s | Early big chance — Andersson fluffs a 0.40 xG opportunity |
| momentum_swing | 6 | verified | 3/3 | – | 8.0s | Westbrook dominates early attacking picture |
| great_save | 7 | verified | 3/3 | – | 7.5s | Delacroix’s reflex stop halts Oakhurst momentum |
| goal | 8 | verified | 3/3 | – | 8.0s | Early penalty puts Harbour City in control |
| control_shift | 9 | corrected | 3/3 | – | 13.0s | Blackwater establish early control and tempo |
| control_shift | 9 | verified | 3/3 | – | 7.6s | Eastmoor seize control early and tilt tempo their way |
| great_save | 12 | verified | 3/3 | – | 8.2s | Crucial reflex save halts Kingsbridge surge |
| great_save | 15 | verified | 3/3 | – | 7.3s | Jansen thwarts 103 km/h strike to keep game level |
| pressing_shift | 21 | verified | 3/3 | – | 10.0s | Eastmoor’s press just let Marlow Heath off the hook |
| pressing_shift | 21 | verified | 3/3 | – | 9.1s | Northgate’s press eases — PPDA triples, control shifts |
| milestone | 26 | corrected | 3/3 | – | 12.5s | Andersson’s first goal kicks Redcliffe into lead |
| wonder_strike | 29 | verified | 3/3 | – | 10.9s | Castell’s 21m strike kills Oakhurst’s comeback hopes |
| red_card | 33 | corrected | 3/3 | – | 12.4s | Red card swings control decisively to Riverside |
| milestone | 47 | verified | 3/3 | – | 7.6s | Benali breaks his duck to pull RDC back into it |
