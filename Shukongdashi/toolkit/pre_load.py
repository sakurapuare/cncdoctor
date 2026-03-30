from __future__ import annotations

from Shukongdashi.core.container import get_container


class _GraphProxy:
    def __getattr__(self, item):
        return getattr(get_container().graph_repository, item)


class _ClassifierProxy:
    def predict(self, message: str):
        return get_container().classifier.classify(message)


neo_con = _GraphProxy()
cnn_model = _ClassifierProxy()
