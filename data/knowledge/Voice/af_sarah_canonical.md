# Historical Voice Archive: af_sarah

> [!CAUTION]
> **SUPERSEDED & DECOMMISSIONED** `[HISTORICAL]`  
> `af_sarah` was used during earlier test phases. It has been **permanently decommissioned** in favor of `af_bella` at native 1.00x speed.  
> **Active Canonical Voice:** [[Voice/af_bella_canonical|af_bella (Bella - US Female)]]  
> **Master Reference:** [[04 — CONTENT PRODUCTION/Narration & Bella Voice Specification|Bella Voice Specification]]  

---

## Historical Context
- **Former Voice Identifier:** `af_sarah`
- **Retirement Reason:** Evaluated as overly formal and rigid for high-retention short-form storytelling. Superseded by Bella's superior warmth and conversational delivery.
- **Erroneous Temporary Lock & Purge:** An earlier hardening change inadvertently whitelisted and defaulted to `af_sarah`. This was identified as a critical defect and surgically rolled back in commit `b4dd8f6306368859f07352adf42deb0b1de6199a`. `af_sarah` is now strictly treated as an unapproved/retired voice that immediately fails closed to `af_bella` across all production, workflow, and resolution paths.