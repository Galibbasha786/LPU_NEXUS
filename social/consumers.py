import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from pymongo.errors import PyMongoError

from . import services

logger = logging.getLogger(__name__)


class SocialChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        session = self.scope.get('session')
        user_id = session.get('lpu_user_id') if session else None
        if not user_id:
            await self.close(code=4401)
            return

        self.chat_id = self.scope['url_route']['kwargs']['chat_id']
        self.group_name = f'social.chat.{self.chat_id}'
        try:
            self.current_user = await self.get_authorized_user(user_id, self.chat_id)
        except services.SocialAccessError:
            await self.close(code=4403)
            return
        except PyMongoError:
            logger.exception('Could not authorize a Social Hub WebSocket')
            await self.close(code=4503)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        group_name = getattr(self, 'group_name', None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict) or content.get('type') != 'message':
            await self.send_json({'type': 'error', 'error': 'Unsupported chat event.'})
            return

        try:
            message = await self.save_message(
                self.current_user['id'],
                self.chat_id,
                content.get('body', ''),
                content.get('gif_url', ''),
            )
        except (ValueError, services.SocialAccessError) as error:
            await self.send_json({'type': 'error', 'error': str(error)})
            return
        except PyMongoError:
            logger.exception('Could not save a WebSocket chat message')
            await self.send_json({
                'type': 'error',
                'error': 'Your message could not be sent. Please try again.',
            })
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'chat.event',
                'payload': self.serialize_message(message),
            },
        )

    async def chat_event(self, event):
        await self.send_json(event['payload'])

    @database_sync_to_async
    def get_authorized_user(self, user_id, chat_id):
        user = services.verified_student(user_id)
        if not user or not services.get_chat(user_id, chat_id):
            raise services.SocialAccessError('This conversation is unavailable.')
        return {
            'id': str(user['_id']),
            'full_name': user.get('full_name', 'LPU student'),
        }

    @database_sync_to_async
    def save_message(self, user_id, chat_id, body, gif_url):
        return services.send_message(user_id, chat_id, body, gif_url)

    @staticmethod
    def serialize_message(message):
        created_at = message.get('created_at')
        return {
            'type': 'message',
            'id': message['id'],
            'sender_id': message['sender_id'],
            'sender_name': message['sender_name'],
            'body': message.get('body', ''),
            'gif_url': message.get('gif_url', ''),
            'media_url': message.get('media_url', ''),
            'media_type': message.get('media_type', ''),
            'shared_post': message.get('shared_post'),
            'created_at': created_at.isoformat() if created_at else '',
        }
