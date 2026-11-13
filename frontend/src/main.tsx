import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <main className="mx-auto max-w-3xl p-6">
        <h1 className="text-2xl font-semibold">UTC Admissions RAG Chatbot</h1>
        <p className="mt-3 text-slate-600">
          Dự án đang được khởi tạo. Các chức năng tư vấn chưa sẵn sàng.
        </p>
      </main>
    </BrowserRouter>
  </StrictMode>,
)
