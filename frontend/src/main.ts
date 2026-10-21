import { createApp, h } from 'vue'

const app = createApp({
    render() {
        return h('main', {
            style: {
                maxWidth: '720px',
                margin: '80px auto',
                padding: '0 24px',
                fontFamily: 'sans-serif',
            },
        }, [
            h('h1', 'Enterprise Agent'),
            h('p', '企业内部业务协作系统'),
            h('p', '当前为 Day1 最小前端占位页'),
            h('p', '登录、渠道、数据库、Agent 和业务流程尚未实现'),
        ])
    },
})

app.mount("#app")