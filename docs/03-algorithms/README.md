# 03. Algorithms — Phoenix WinNonlin 호환 사양

## 원칙

1. **매뉴얼이 진실의 원천**
   모든 알고리즘 구현은 `reference/` 폴더의 Phoenix WinNonlin 매뉴얼(5.3 / 6.4 / 8.3) 및 Phoenix 1.4 Data Tools Guide를 기준으로 합니다. 각 알고리즘 문서는 해당 매뉴얼의 **섹션 번호와 페이지**를 인용해야 합니다.

2. **버전 인식**
   동일한 파라미터라도 WinNonlin 버전에 따라 기본 동작이 다를 수 있습니다. `winnonlin_version` 옵션으로 모든 분기를 명시합니다. 차이는 [04-winnonlin-version-matrix.md](../04-winnonlin-version-matrix.md)에 집계.

3. **수식 우선, 코드 후행**
   모든 알고리즘은 먼저 LaTeX 수식 + 의사코드(pseudocode)로 명세하고 그 다음 Python 구현을 작성합니다.

4. **결정론적 (Deterministic)**
   동일 입력 + 동일 옵션 + 동일 버전 → 항상 동일 결과. 난수 사용 금지(부트스트랩 등은 seed 명시).

5. **단위 변환 금지 (Implicit)**
   알고리즘 내부는 정규화된 단위만 받음. 변환은 ingest 레이어에서만 수행.

---

## 📂 알고리즘 문서 목차

| 문서 | 도입 버전 | 핵심 내용 |
|---|---|---|
| [01-nca-parameters.md](01-nca-parameters.md) | v0.1 | NCA 파라미터 전체 사전 + 수식 |
| [02-auc-methods.md](02-auc-methods.md) | v0.1 | Linear / Log / Linear-up Log-down |
| [03-lambda-z-selection.md](03-lambda-z-selection.md) | v0.1 | Best Fit / Adj R² / Manual |
| [04-bloq-handling.md](04-bloq-handling.md) | v0.1 | BLOQ / Missing / 정책 매트릭스 |
| [05-partial-auc.md](05-partial-auc.md) | v0.1 | Partial AUC 보간 |
| [06-steady-state.md](06-steady-state.md) | v0.2 | Tau, Cavg, fluctuation, accumulation |
| [07-bioequivalence.md](07-bioequivalence.md) | v0.2 | TOST, 90% CI, crossover ANOVA |
| [08-compartmental-models.md](08-compartmental-models.md) | v0.3 | 1/2/3-cmt IV/PO, Michaelis-Menten |
| [09-pkpd-models.md](09-pkpd-models.md) | v0.4 | Emax / Effect compartment / IDR |

---

## 🔖 인용 형식 규약

알고리즘 문서에서 매뉴얼 참조는 다음 형식을 사용합니다:

```
> 📖 WinNonlin 6.4 §7.2.3 (p. 142): "AUC is calculated using the linear-up/log-down method..."
```

코드 docstring 에서도 동일:

```python
def auc_linear_up_log_down(t, c, version="6.4"):
    """
    Compute AUC using linear-up/log-down trapezoidal rule.

    Refs:
    - Phoenix WinNonlin 6.4 User's Guide §7.2.3 (p. 142)
    - WinNonlin 5.3 User's Guide §6.1.4 (p. 118) — equivalent algorithm
    - WinNonlin 8.3 User's Guide §8.3.1 (p. 165) — added boundary clarification
    """
```

> **TODO 마커**: 매뉴얼 페이지를 아직 검증하지 않은 항목은 `📋 TODO: cite manual` 로 표기.
