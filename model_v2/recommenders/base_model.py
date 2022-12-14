from typing import Type

from torch import nn

from loader.global_setting import Setting
from model_v2.news.base_model import BaseNewsModel
from model_v2.user.base_model import BaseUserModel
from model_v2.utils.column_map import ColumnMap
from model_v2.utils.embedding_manager import EmbeddingManager
from model_v2.utils.nr_depot import NRDepot
from utils.printer import printer, Color
from utils.shaper import Shaper
from utils.structure import Structure


class BaseRecommenderConfig:
    def __init__(
            self,
            user_config,
            news_config=None,
            use_news_content: bool = True,
    ):
        self.news_config = news_config
        self.user_config = user_config
        self.use_news_content = use_news_content

        if self.use_news_content and not self.news_config:
            raise ValueError('news_config is required when use_news_content is True')


class BaseRecommender(nn.Module):
    config_class = BaseRecommenderConfig
    news_encoder_class = None  # type: Type[BaseNewsModel]
    user_encoder_class = None  # type: Type[BaseUserModel]

    def __init__(
            self,
            config: BaseRecommenderConfig,
            column_map: ColumnMap,
            embedding_manager: EmbeddingManager,
            user_nrd: NRDepot,
            news_nrd: NRDepot,
    ):
        super().__init__()

        self.config = config  # type: BaseRecommenderConfig
        self.print = printer[(self.__class__.__name__, '|', Color.MAGENTA)]

        self.column_map = column_map  # type: ColumnMap
        self.embedding_manager = embedding_manager
        self.embedding_table = embedding_manager.get_table()

        self.clicks_col = column_map.clicks_col
        self.candidate_col = column_map.candidate_col
        self.label_col = column_map.label_col
        self.clicks_mask_col = column_map.clicks_mask_col
        self.user_encoder = self.user_encoder_class(config.user_config, nrd=user_nrd)
        if self.config.use_news_content:
            self.news_encoder = self.news_encoder_class(config.news_config, nrd=news_nrd)

        self.shaper = Shaper()

    def get_content(self, batch, col):
        news_content = self.shaper.transform(batch[col])
        attention_mask = news_content['attention_mask'].to(Setting.device)
        # batch_size * click_size, max_seq_len, embedding_dim
        news_content = self.news_encoder.inputer.get_embeddings(news_content, embedding_manager=self.embedding_manager)

        news_content = self.news_encoder(news_content, mask=attention_mask)  # batch_size * click_size, embedding_dim
        news_content = self.shaper.recover(news_content)
        return news_content

    def forward(self, batch):
        assert self.config.use_news_content, 'not implemented'
        candidates = self.get_content(batch, self.candidate_col)  # batch_size, candidate_size, embedding_dim
        clicks = self.get_content(batch, self.clicks_col)  # batch_size, click_size, embedding_dim

        user_embedding = self.user_encoder.inputer.embedding_processor(
            embeddings=clicks,
            mask=batch[self.clicks_mask_col].to(Setting.device)
        )
        return self.user_encoder(
            user_embedding,
            mask=batch[self.clicks_mask_col].to(Setting.device),
            candidates=candidates,
            labels=batch[self.label_col].to(Setting.device),
        )

    def __str__(self):
        return self.__class__.__name__
