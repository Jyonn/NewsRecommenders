from model_v2.common.attention_fusion_model import AttentionFusionOperator
from model_v2.inputer.cat_inputer import CatInputer
from model_v2.interaction.negative_sampling import NegativeSampling
from model_v2.user.base_model import BaseUserModel


class UserAttentionFusionModel(BaseUserModel):
    operator_class = AttentionFusionOperator
    interaction = NegativeSampling
    inputer_class = CatInputer

    def forward(self, embeddings, mask=None, **kwargs):
        candidates = kwargs['candidates']
        user_embedding = self.operator(embeddings, mask=mask, **kwargs)
        return self.interaction.predict(user_embedding, candidates, labels=None, is_training=self.training)
