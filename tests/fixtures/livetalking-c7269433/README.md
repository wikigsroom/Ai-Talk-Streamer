# Pinned upstream source fixtures

These unmodified Apache-2.0 source files are from
[lipku/LiveTalking at c7269433a2b6ecebcd9342445d2ecc882c98b0da](https://github.com/lipku/LiveTalking/tree/c7269433a2b6ecebcd9342445d2ecc882c98b0da/avatars).
Their original copyright and license headers are retained. They are CPU-test
fixtures, not another installed avatar runtime.
The complete [Apache-2.0 license](../../../LICENSE) is distributed with this repository.

| File | SHA-256 |
|---|---|
| base_avatar.py | f1e6538fe3c9f16f402cd69f83e3774ea3dfa74d95050d08fb2884acbea435dc |
| musetalk_avatar.py | f0ffbb3975e1fa92cd1aab6ee035bfbb3381cc6aa52d0bdd89166309493a8bd5 |

The K02 tests patch the actual pinned sources, check idempotency, then execute
the patched queue-consumer and paste-back methods without importing Torch.
