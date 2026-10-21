# Newsroom evaluation

Run `newsroom-md11-13-20261022-020532` on 2026-10-22 02:19: 72 moments from simulated matchday(s) 11, 12, 13, rendered in en, es, ar. Analyst `gpt-5-mini`, Host `gpt-4.1-mini`, judge `gpt-4.1-mini`.

## Quality gates

| Metric | Value | Gate | |
|---|---|---|---|
| verified rate | 100% | >= 0.9 | ✅ |
| final claim accuracy | 100% | >= 0.98 | ✅ |
| planted claim catch rate | 100% | >= 0.95 | ✅ |
| planted fabrication catch rate | 100% | >= 0.9 | ✅ |
| control false alarm rate | 0% | <= 0.1 | ✅ |
| near miss catch rate | 100% | >= 0.95 | ✅ |
| wrong subject catch rate | 100% | >= 0.95 | ✅ |
| varied fabrication catch rate | 97% | >= 0.9 | ✅ |
| rendition number catch rate | 98% | >= 0.95 | ✅ |
| tolerance false alarm rate | 0% | <= 0.1 | ✅ |
| renditions with untraceable numbers | 0% | <= 0.02 | ✅ |
| language coverage | 100% | >= 0.95 | ✅ |
| latency p95 s | 12.87 | <= 30.0 | ✅ |
| groundedness | 4.91 | >= 3.5 | ✅ |
| relevance | 5.00 | >= 3.5 | ✅ |
| coherence | 4.54 | >= 3.5 | ✅ |

## Details

- First-pass clean (no Verifier corrections needed): 83%; rewrites per item: 0.17
- Claims checked against live data: 216 of 216 published claims matched (within the Verifier's tolerance: 5%, or 0.02 for small decimals / 0.5 for counts)
- Latency p50 8.1s, p95 12.9s (Analyst + Verifier + 3-language Host, end to end)
- AI judges (1-5): groundedness 4.91, relevance 5.00, coherence 4.55, fluency 4.01
- Content safety defect rates: {'violence_defect_rate': 0.0, 'self_harm_defect_rate': 0.0, 'sexual_defect_rate': 0.0, 'hate_unfairness_defect_rate': 0.0}
- Foundry evaluation run: https://ai.azure.com/resource/build/evaluation/939105f3-ffba-4559-ae90-2a97158baca4?wsid=/subscriptions/991df65a-d37a-4d15-9414-3a448ce23817/resourceGroups/rg-footballytics-dev/providers/Microsoft.CognitiveServices/accounts/fbx-ai-5dn4hvp4nnbzs/projects/footballytics&tid=c46e3e34-90fe-4e13-9135-bdf6c03b41be

## Planted-error tests

Every published item is attacked several ways at the moment it is produced. Overall: 567 of 574 planted errors caught (95% CI 98%–99%).

| Test | What is planted | Caught | 95% CI |
|---|---|---|---|
| planted claim | a claim inflated by 50% | 72/72 | 95%–100% |
| near miss | a claim just outside the Verifier's tolerance | 72/72 | 95%–100% |
| wrong subject | the right number credited to the wrong player or team | 70/70 | 95%–100% |
| fixed fabrication | the fixed fabricated sentence | 72/72 | 95%–100% |
| varied fabrication | a randomly drawn fabricated sentence | 70/72 | 90%–99% |
| rendition number | a fabricated number in a translated rendition (en, es, Arabic digits) | 211/216; removed before air 211/216 | 95%–99% |

| False-alarm control | What is checked | Flagged | 95% CI |
|---|---|---|---|
| untouched item | the untouched verified item | 0/72 | 0%–5% |
| within tolerance | a claim moved but kept within tolerance | 0/72 | 0%–5% |

## Known blind spots

- **Small whole numbers.** The number audit lets 0-11 through, because prose uses them for counts and ordinals ("two defenders", "the 2nd goal"). A fabricated sentence using only such numbers was caught 0/72 times.
- **Attribution in prose.** Structured claims are checked per player and team, but a correct number credited to the wrong player in the prose itself is not.
- **Statements without numbers** ("his first goal for the club") are only assessed by the AI judge.
- **The judge** is `gpt-4.1-mini`, the same model as the Host.

## Items

| Kind | Min | Status | Claims ok | Untraceable numbers | Latency | Headline |
|---|---|---|---|---|---|---|
| high_turnover | 1 | verified | 3/3 | – | 10.8s | Rahman’s early interception halts Northgate momentum |
| line_breaking_pass | 1 | verified | 3/3 | – | 10.8s | Early 45‑metre line‑breaking ball splits defence |
| line_breaking_pass | 1 | verified | 3/3 | – | 10.2s | Early line-breaking cross forces attention |
| momentum_swing | 2 | verified | 3/3 | – | 8.5s | Falconridge dominates early attack, seizing momentum |
| penalty_awarded | 2 | verified | 3/3 | – | 7.6s | Early penalty hands Rahman a match-defining chance |
| high_turnover | 3 | verified | 3/3 | – | 8.5s | Early high turnover sparks HFP counter chance |
| goal | 3 | corrected | 3/3 | – | 8.5s | Early penalty gives Falconridge an immediate lead |
| momentum_swing | 4 | verified | 3/3 | – | 7.5s | Early momentum swing: Kingsbridge seizes attacking control |
| goal | 4 | verified | 3/3 | – | 7.1s | Early corner header hands leaders the lead |
| goal | 4 | verified | 3/3 | – | 6.7s | Early penalty gives Thornbury crucial lead |
| big_chance | 5 | verified | 3/3 | – | 7.5s | Big chance wasted by Andersson inside box |
| momentum_swing | 6 | verified | 3/3 | – | 8.9s | Westbrook seizes early control after flurry of pressure |
| great_save | 7 | verified | 3/3 | – | 92.7s | Huge early save preserves Thornbury lead |
| goal | 8 | verified | 3/3 | – | 7.7s | Early penalty gives Harbour City the lead |
| control_shift | 9 | verified | 3/3 | – | 7.4s | Blackwater seizes early control and momentum |
| control_shift | 9 | verified | 3/3 | – | 11.3s | Eastmoor seize early control and dictate tempo |
| great_save | 12 | corrected | 3/3 | – | 10.6s | Crucial reflex denies equaliser after KGA surge |
| great_save | 15 | verified | 3/3 | – | 7.2s | Jansen’s reflex stop prevents early Redcliffe breakthrough |
| pressing_shift | 21 | verified | 3/3 | – | 8.2s | Eastmoor's press just eased — PPDA spikes massively |
| pressing_shift | 21 | corrected | 3/3 | – | 10.3s | Northgate ease pressure, PPDA jumps sharply |
| milestone | 26 | verified | 3/3 | – | 7.4s | Andersson breaks Redcliffe drought with timely opener |
| wonder_strike | 29 | verified | 3/3 | – | 7.5s | Castell's long strike kills Oakhurst momentum |
| red_card | 33 | corrected | 3/3 | – | 10.7s | Port Ellis reduced to 10 men at 1-0, 33rd minute |
| milestone | 47 | verified | 3/3 | – | 8.6s | Benali breaks drought to halve deficit early second half |
| line_breaking_pass | 1 | verified | 3/3 | – | 8.1s | Spectacular 35m line-breaker splits nine defenders |
| high_turnover | 1 | verified | 3/3 | – | 7.2s | Early interception gives Northgate instant threat |
| line_breaking_pass | 1 | verified | 3/3 | – | 9.5s | Early 30m line-breaking pass sets tone for Redcliffe |
| goal | 3 | verified | 3/3 | – | 7.2s | Early cross creates shock opening goal |
| milestone | 3 | verified | 3/3 | – | 28.6s | Early opener: Rui Silva-Reid breaks his duck |
| high_turnover | 3 | corrected | 3/3 | – | 9.5s | Early high turnover sets up instant danger for Kingsbridge |
| goal | 3 | verified | 3/3 | – | 5.3s | Early Rinaldi strike rocks the hosts |
| milestone | 3 | verified | 3/3 | – | 7.0s | Early strike takes Rinaldi to ten for the season |
| great_save | 6 | verified | 3/3 | – | 6.7s | Early screamer denied by Sorensen |
| momentum_swing | 7 | verified | 3/3 | – | 7.3s | Ironvale seizes early attacking control |
| great_save | 8 | corrected | 3/3 | – | 8.8s | Early scream saved by Sami Jansen |
| great_save | 8 | verified | 3/3 | – | 6.1s | Crucial early save halts Redcliffe momentum |
| control_shift | 9 | verified | 3/3 | – | 8.2s | Eastmoor grab early control, forcing Ashcombe onto back foot |
| control_shift | 9 | verified | 3/3 | – | 8.5s | Thornbury seize control early, pinning Marlow back |
| momentum_swing | 11 | verified | 3/3 | – | 8.2s | Fenwick seize control after shaky start |
| big_chance | 12 | verified | 3/3 | – | 9.0s | Huge early big chance blocked inside box |
| goal | 13 | verified | 3/3 | – | 8.0s | Chen’s 13th‑minute strike breaks deadlock |
| pressing_shift | 21 | verified | 3/3 | – | 8.9s | Ironvale eases off pressing; Greyhaven gains breathing space |
| pressing_shift | 21 | verified | 3/3 | – | 9.1s | Eastmoor’s press suddenly cuts opponent’s time on ball |
| momentum_swing | 21 | verified | 3/3 | – | 9.3s | Silverlake seizes attacking control amid chaotic spell |
| penalty_awarded | 21 | verified | 3/3 | – | 5.9s | High-value penalty offers quick equaliser chance |
| goal | 21 | verified | 3/3 | – | 12.9s | Low-xG long-range opener breaks Rangers’ control |
| red_card | 22 | corrected | 3/3 | – | 10.2s | Red card swings balance to Thornbury Wanderers |
| big_chance | 28 | verified | 3/3 | – | 6.6s | Huge 2m sitter denied — let-off for Stonebridge |
| line_breaking_pass | 1 | verified | 3/3 | – | 12.4s | Risky 34m line-breaker splits six defenders |
| high_turnover | 1 | verified | 3/3 | – | 6.6s | Early high turnover wins Greyhaven instant threat |
| line_breaking_pass | 2 | verified | 3/3 | – | 9.5s | Early 6‑man bypass shifts momentum to Northgate |
| great_save | 2 | verified | 3/3 | – | 7.0s | Early thunderbolt denied by Venter |
| goal | 2 | verified | 3/3 | – | 5.5s | Early free‑kick header hands leaders an instant edge |
| high_turnover | 2 | verified | 3/3 | – | 5.6s | Early high turnover gifts Ironvale a chance |
| momentum_swing | 3 | verified | 3/3 | – | 7.3s | Thornbury seize early attacking control |
| momentum_swing | 4 | verified | 3/3 | – | 7.3s | Highfield dominate early momentum on rush of chances |
| great_save | 5 | corrected | 3/3 | – | 10.3s | Early reflex stop preserves 0-0 tense balance |
| great_save | 5 | verified | 3/3 | – | 5.0s | Early stop: big chance denied at 5 minutes |
| goal | 5 | verified | 3/3 | – | 5.3s | Rinaldi’s early strike kills Marlow Heath hope |
| goal | 6 | corrected | 3/3 | – | 10.7s | Obi’s long strike breaks the deadlock early |
| control_shift | 9 | verified | 3/3 | – | 7.6s | Chaotic opening: game slipping out of control |
| control_shift | 9 | verified | 3/3 | – | 7.3s | Oakhurst seize control after nervy opening minutes |
| goal | 10 | verified | 3/3 | – | 8.7s | Yamamoto’s low-xG opener breaks the deadlock |
| milestone | 10 | verified | 3/3 | – | 6.5s | Yamamoto’s early strike doubles his season tally |
| big_chance | 10 | verified | 3/3 | – | 6.2s | Bellamy’s blocked big chance swings early momentum |
| momentum_swing | 12 | verified | 3/3 | – | 7.3s | Thornbury seizes attacking control early |
| big_chance | 20 | corrected | 3/3 | – | 10.6s | Big chance stopped as away pressure continues |
| pressing_shift | 21 | verified | 3/3 | – | 7.7s | Eastmoor's press loosens — PPDA jumps, control drifts |
| pressing_shift | 21 | corrected | 3/3 | – | 10.4s | Greyhaven ease off the press, ceding control to Silverlake |
| big_chance | 25 | verified | 3/3 | – | 7.8s | Huge chance blocked after Sato’s dangerous delivery |
| red_card | 25 | corrected | 3/3 | – | 9.8s | Red card leaves Harbour City a man down at 25' |
| milestone | 51 | verified | 3/3 | – | 22.5s | Andersson’s opener is his fifth of the season |
